"""Qt desktop workbench. Network work runs on a single background worker."""
import argparse
from contextlib import contextmanager
from pathlib import Path
import sys
import time
import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets as W
from yokogawa_tool.core.waveform import load_file, export_csv, export_wvf, wvf_paths, save_session, COLORS
from yokogawa_tool.core.analysis import expression_trace, transform, spectrum
from yokogawa_tool.acquisition.instrument import DL1640
from yokogawa_tool.gui.themes import THEMES, stylesheet as theme_stylesheet, button_stylesheet
from yokogawa_tool.gui.instrument_panel import InstrumentPanel
from yokogawa_tool.gui.view_state import restore_view, waveform_bounds
from yokogawa_tool.acquisition.screen import fetch_screen
from yokogawa_tool.gui.screen_panel import ScreenPanel
from yokogawa_tool.gui.rendering import WaveformPlotItem
from yokogawa_tool.core.measurements import METRICS, DEFAULT_METRICS, measure

pg.setConfigOptions(antialias=True, segmentedLineMode="on", background="#101720", foreground="#bdcad9")

STYLE = """
QMainWindow, QDialog { background: #141d29; color: #e2eaf3; }
QWidget { color: #d8e2ef; font-size: 13px; }
QGroupBox { border: 1px solid #344356; border-radius: 7px; margin-top: 12px; padding: 12px 8px 8px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #89c8ed; }
QPushButton, QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox { background: #223044; border: 1px solid #3b4c62; border-radius: 4px; padding: 6px; }
QPushButton:hover { background: #30445d; border-color: #72b8e8; }
QPushButton:disabled { color: #607185; background: #1b2533; }
QPushButton[accent="true"] { background: #246e94; color: white; }
QTableWidget { background: #101720; alternate-background-color: #192331; border: 1px solid #344356; gridline-color: #273448; }
QHeaderView::section { background: #223044; padding: 7px; border: 0; color: #9cb3cd; }
QToolBar { border: 0; background: #1b2736; padding: 6px; spacing: 7px; }
QStatusBar { background: #1b2736; }
QLabel[muted="true"] { color: #8fa5bd; }
QTabWidget::pane { border: 1px solid #344356; }
QTabBar::tab { background: #223044; padding: 8px 16px; }
QTabBar::tab:selected { background: #35516c; }
QCheckBox { spacing: 6px; }
QScrollArea { border: 0; }
QToolTip { background: #223044; color: #e2eaf3; border: 1px solid #6086a4; }
"""


def configure_application(application, theme="dark"):
    theme = theme if theme in THEMES else "dark"
    colors = THEMES[theme]
    application.setStyle("Fusion")
    palette = QtGui.QPalette()
    for role, color in {
        QtGui.QPalette.Window: colors["bg"], QtGui.QPalette.WindowText: colors["text"],
        QtGui.QPalette.Base: colors["base"], QtGui.QPalette.AlternateBase: colors["alternate"],
        QtGui.QPalette.Text: colors["text"], QtGui.QPalette.Button: colors["button"],
        QtGui.QPalette.ButtonText: colors["text"], QtGui.QPalette.Highlight: colors["primary"],
        QtGui.QPalette.HighlightedText: "#ffffff", QtGui.QPalette.ToolTipBase: "#223044",
        QtGui.QPalette.ToolTipText: "#e2eaf3",
    }.items():
        palette.setColor(role, QtGui.QColor(color))
    application.setPalette(palette)
    application.setStyleSheet(STYLE + (theme_stylesheet(theme) if theme != "dark" else "") + button_stylesheet())


def button(text, callback, accent=False):
    widget = W.QPushButton(text)
    widget.setProperty("accent", accent)
    if "Math" in text or "演算" in text or "FFT" in text:
        widget.setProperty("role", "math")
    widget.clicked.connect(callback)
    return widget


def fmt(value, unit=""):
    if not np.isfinite(value):
        return "—"
    return pg.siFormat(value, precision=5, suffix=unit)


class Worker(QtCore.QThread):
    result = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.result.emit(self.function())
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class WaveformViewBox(pg.ViewBox):
    """Restrict wheel zoom without restricting pan or rectangle selection."""
    wheel_axis = 0

    def wheelEvent(self, event, axis=None):
        self.enableAutoRange(axis=1-self.wheel_axis, enable=False)
        super().wheelEvent(event, axis=self.wheel_axis)


class OverviewViewBox(pg.ViewBox):
    """Keep the overview intact while wheel gestures zoom its selected range."""
    zoom_requested = QtCore.Signal(float, float)

    def wheelEvent(self, event, axis=None):
        factor = 1.02 ** (event.delta() * self.state['wheelScaleFactor'])
        anchor = self.mapSceneToView(event.scenePos()).x()
        self.zoom_requested.emit(factor, anchor)
        event.accept()


class MainWindow(W.QMainWindow):
    display_restore_failed = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DL1640 Waveform Workbench")
        self.resize(1440, 950)
        self.setMinimumSize(1000, 700)
        self.traces = []
        self.curves = []
        self.worker = None
        self._worker_action = None
        self._live_device = None
        self._network_started = 0.
        self._pending_run_toggle = False
        self._pending_run_target = None
        self._run_in_flight = False
        self._run_in_flight_target = None
        self._stopped_frame_valid = False
        self.screen_enabled = False
        self._screen_generation = 0
        self._screen_timer = QtCore.QTimer(self)
        self._screen_timer.setSingleShot(True)
        self._screen_timer.timeout.connect(self.poll_screen)
        self.dirty = False
        self.windows = []
        self.live_enabled = False
        self._disconnect_requested = False
        self._disconnect_capture_waiting = False
        self._live_generation = 0
        self._live_first_frame = True
        self._live_count = 0
        self._live_started = 0
        self._live_timer = QtCore.QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.timeout.connect(self.poll_live)
        self.settings = QtCore.QSettings("YokogawaTool", "WaveformWorkbench")
        self._stats_cache = {}
        self._readout_timer = QtCore.QTimer(self)
        self._readout_timer.setSingleShot(True)
        self._readout_timer.setInterval(60)
        self._readout_timer.timeout.connect(self.update_readouts)
        self._build()
        self.display_restore_failed.connect(self.report_display_restore_failure)
        self.run_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Space"), self)
        self.run_shortcut.setAutoRepeat(False)
        self.run_shortcut.activated.connect(self.toggle_instrument)
        self.apply_theme(str(self.settings.value("theme", "dark")))
        self.setAcceptDrops(True)
        self.statusBar().showMessage("WVF/HDRまたはCSVを開いてください。ファイルのドラッグ＆ドロップも使えます。")

    def _build(self):
        toolbar = self.addToolBar("ファイルと表示")
        toolbar.setMovable(False)
        self.sidebar_dock = W.QDockWidget("操作パネル", self)
        self.sidebar_dock.setObjectName("operationsPanel")
        self.sidebar_dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea)
        self.sidebar_dock.setFeatures(W.QDockWidget.DockWidgetClosable)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.sidebar_dock)
        self.sidebar_action = self.sidebar_dock.toggleViewAction()
        self.sidebar_action.setText("左パネル")
        self.sidebar_action.setShortcut("Ctrl+B")
        self.sidebar_action.setToolTip("左の操作パネルを表示／非表示 (Ctrl+B)")
        toolbar.addAction(self.sidebar_action)
        toolbar.addSeparator()
        self.run_action = toolbar.addAction("実機 RUN/STOP [Space]", self.toggle_instrument)
        self.run_action.setToolTip("実機の測定を開始／停止します。波形読み出し中も操作できます。")
        toolbar.addSeparator()
        self.file_actions = {}
        for title, shortcut, callback in [
            ("ファイルを開く", "Ctrl+O", self.open_dialog),
            ("セッション保存", "Ctrl+S", self.save_dialog),
            ("CSV出力", "Ctrl+E", self.csv_dialog),
            ("WVF/HDR出力", "Ctrl+Shift+E", self.wvf_dialog),
            ("画像保存", "", self.image_dialog),
            ("全体表示", "Home", self.fit_current_view),
        ]:
            action = toolbar.addAction(title, callback)
            self.file_actions[title] = action
            if shortcut:
                action.setShortcut(shortcut)
        toolbar.addSeparator()
        toolbar.addWidget(W.QLabel("ホイール"))
        self.wheel_axis_combo = W.QComboBox()
        self.wheel_axis_combo.addItem("横のみ（時間）", "x")
        self.wheel_axis_combo.addItem("縦のみ（振幅）", "y")
        self.wheel_axis_combo.setToolTip("メイン波形のホイール拡大軸。下段Overviewは常に時間軸のみ。")
        saved_axis = str(self.settings.value("wheel_axis", "x"))
        self.wheel_axis_combo.setCurrentIndex(1 if saved_axis == "y" else 0)
        toolbar.addWidget(self.wheel_axis_combo)
        toolbar.addSeparator()
        self.rect_mode = W.QCheckBox("範囲をドラッグして拡大")
        self.rect_mode.toggled.connect(lambda on: self.plot.getViewBox().setMouseMode(
            pg.ViewBox.RectMode if on else pg.ViewBox.PanMode))
        toolbar.addWidget(self.rect_mode)
        toolbar.addWidget(button("使い方", self.help_dialog))
        toolbar.addSeparator()
        toolbar.addWidget(W.QLabel("テーマ"))
        self.theme_combo = W.QComboBox()
        for key, theme in THEMES.items():
            self.theme_combo.addItem(theme["label"], key)
        toolbar.addWidget(self.theme_combo)
        self.theme_combo.currentIndexChanged.connect(lambda _: self.apply_theme(self.theme_combo.currentData()))

        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(290)
        scroll.setMaximumWidth(420)
        sidebar = W.QWidget()
        self.side = W.QVBoxLayout(sidebar)
        scroll.setWidget(sidebar)
        self.sidebar_tabs = W.QTabWidget()
        self.sidebar_tabs.addTab(scroll, "波形・解析")
        self.sidebar_dock.setWidget(self.sidebar_tabs)

        self.heading = W.QLabel("DL1640  /  WORKBENCH")
        self.side.addWidget(self.heading)
        self.file_label = W.QLabel("波形ファイル未読込")
        self.file_label.setWordWrap(True)
        self.file_label.setProperty("muted", True)
        self.side.addWidget(self.file_label)

        display_group = W.QGroupBox("描画")
        display_layout = W.QVBoxLayout(display_group)
        self.antialias_checkbox = W.QCheckBox("アンチエイリアス（線を滑らかに表示）")
        self.antialias_checkbox.setChecked(self.settings.value("antialias", True, type=bool))
        self.antialias_checkbox.setToolTip("線の階段状のギザギザを軽減します。波形データ・測定値は変わりません。重い場合はOFFにできます。")
        display_layout.addWidget(self.antialias_checkbox)
        self.interpolation_combo = W.QComboBox()
        for label, key in (("直線（補間なし）", "linear"), ("階段（サンプル保持）", "step"),
                           ("曲線（単調3次補間）", "cubic")):
            self.interpolation_combo.addItem(label, key)
        index = self.interpolation_combo.findData(str(self.settings.value("interpolation", "linear")))
        self.interpolation_combo.setCurrentIndex(max(index, 0))
        self.interpolation_combo.setToolTip("表示用の補間です。Measure・Math・保存データは元サンプルを使用します。")
        display_layout.addWidget(self.interpolation_combo)
        self.interpolation_combo.currentIndexChanged.connect(self.set_interpolation)
        self.dark_plot = W.QCheckBox("波形画面は常に暗色")
        self.dark_plot.setChecked(self.settings.value("dark_plot", False, type=bool))
        self.dark_plot.toggled.connect(self.set_dark_plot)
        display_layout.addWidget(self.dark_plot)
        self.side.addWidget(display_group)

        ch_group = W.QGroupBox("CHANNELS  ·  表示と色")
        self.channel_layout = W.QVBoxLayout(ch_group)
        self.side.addWidget(ch_group)

        math_group = W.QGroupBox("MATH  ·  波形演算")
        self.math_group = math_group
        layout = W.QVBoxLayout(math_group)
        self.expression = W.QLineEdit("CH1 - CH2")
        self.expression.setPlaceholderText("例: (CH1 - CH2) * 10")
        layout.addWidget(self.expression)
        layout.addWidget(button("数式からMathを追加", self.add_expression, True))
        note = W.QLabel("+ − * / **、abs / sqrt / sin / cos\n式の単位はarb（任意単位）です。")
        note.setWordWrap(True)
        note.setProperty("muted", True)
        layout.addWidget(note)
        self.math_source = W.QComboBox()
        layout.addWidget(self.math_source)
        self.math_operation = W.QComboBox()
        self.math_operation.addItems(["微分", "積分", "移動平均"])
        layout.addWidget(self.math_operation)
        self.smooth_window = W.QSpinBox()
        self.smooth_window.setRange(1, 100001)
        self.smooth_window.setValue(11)
        self.smooth_window.setPrefix("移動平均の窓幅: ")
        layout.addWidget(self.smooth_window)
        row = W.QHBoxLayout()
        row.addWidget(button("演算を追加", self.add_transform))
        row.addWidget(button("FFTを表示", self.show_fft))
        layout.addLayout(row)
        self.side.addWidget(math_group)

        protocol_group = W.QGroupBox("PROTOCOL · 取得済み波形の解析")
        protocol_layout = W.QVBoxLayout(protocol_group)
        protocol_layout.addWidget(button("プロトコル解析 · EnDat / UART / SPI…", self.show_protocol))
        protocol_note = W.QLabel("STOP後の元サンプルを使用します。\nEnDatは内蔵、その他はsigrok-cliが必要です。")
        protocol_note.setWordWrap(True)
        protocol_layout.addWidget(protocol_note)
        self.side.addWidget(protocol_group)

        self.side.addStretch()

        self.instrument_panel = InstrumentPanel(self.settings)
        self.instrument_panel.requested.connect(self.network)
        self.instrument_panel.live_requested.connect(self.request_live)
        self.instrument_panel.invalidated.connect(self.instrument_invalidated)
        instrument_scroll = W.QScrollArea()
        instrument_scroll.setWidgetResizable(True)
        instrument_scroll.setMinimumWidth(290)
        instrument_scroll.setMaximumWidth(420)
        instrument_scroll.setWidget(self.instrument_panel)
        self.sidebar_tabs.addTab(instrument_scroll, "実機操作")
        self.sidebar_tabs.currentChanged.connect(lambda index: self.instrument_panel.ensure_loaded() if index == 1 else None)
        self.host, self.port = self.instrument_panel.host, self.instrument_panel.port
        self.username, self.password = self.instrument_panel.username, self.instrument_panel.password
        self.network_label = self.instrument_panel.status

        center = W.QWidget()
        layout = W.QVBoxLayout(center)
        self.plot = pg.PlotWidget(viewBox=WaveformViewBox())
        self.plot.getViewBox().sigRangeChangedManually.connect(self.mark_dirty)
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.setLabel("left", "Amplitude (CHごとの単位は表を参照)")
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.plot.addLegend(offset=(15, 10))
        self.plot.setClipToView(True)
        self.plot.setDownsampling(auto=True, mode="peak")
        self.plot.setTitle("波形を開いて解析を開始", color="#8fa5bd", size="13pt")
        layout.addWidget(self.plot, 5)
        self.cursor_a = pg.InfiniteLine(pos=0, angle=90, movable=True,
                                        pen=pg.mkPen("#c1d9f1", style=QtCore.Qt.DashLine),
                                        label="A", labelOpts={"position": 0.95})
        self.cursor_b = pg.InfiniteLine(pos=0.001, angle=90, movable=True,
                                        pen=pg.mkPen("#89c8ed", style=QtCore.Qt.DashLine),
                                        label="B", labelOpts={"position": 0.88})
        for cursor in (self.cursor_a, self.cursor_b):
            cursor.setZValue(1000)
            self.plot.addItem(cursor, ignoreBounds=True)
            cursor.sigPositionChanged.connect(self.schedule_readouts)
            cursor.sigPositionChangeFinished.connect(self.mark_dirty)
        self.cursor_label = W.QLabel("カーソルA/Bをドラッグすると、最寄りサンプルの値を表示します。")
        self.cursor_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self.cursor_label)
        row = W.QHBoxLayout()
        row.addWidget(button("A/Bを表示範囲に配置", self.place_cursors))
        row.addWidget(button("A–B範囲を拡大", self.zoom_cursors))
        self.visible_stats = W.QCheckBox("測定値は表示中の時間範囲")
        self.visible_stats.setChecked(True)
        self.visible_stats.toggled.connect(self.update_readouts)
        row.addWidget(self.visible_stats)
        self.measure_ab = W.QCheckBox("A–B間を測定")
        self.measure_ab.toggled.connect(lambda enabled: self.visible_stats.setEnabled(not enabled))
        self.measure_ab.toggled.connect(self.update_readouts)
        row.addWidget(self.measure_ab)
        self.measure_menu = W.QMenu(self)
        self.measurement_actions = {}
        selected = self.settings.value("measurement_items", DEFAULT_METRICS)
        selected = [selected] if isinstance(selected, str) else selected
        for metric in METRICS:
            action = self.measure_menu.addAction(metric.title)
            action.setCheckable(True)
            action.setChecked(metric.key in selected)
            action.toggled.connect(self.measurement_selection_changed)
            self.measurement_actions[metric.key] = action
        self.measure_button = W.QToolButton()
        self.measure_button.setText("Measure · 測定項目")
        self.measure_button.setMenu(self.measure_menu)
        self.measure_button.setPopupMode(W.QToolButton.InstantPopup)
        row.addWidget(self.measure_button)
        row.addStretch()
        layout.addLayout(row)
        overview_view = OverviewViewBox()
        overview_view.zoom_requested.connect(self.zoom_from_overview)
        self.overview = pg.PlotWidget(viewBox=overview_view)
        self.overview.setMaximumHeight(110)
        self.overview.setMinimumHeight(85)
        self.overview.setLabel("bottom", "Overview", units="s")
        self.overview.setMouseEnabled(x=False, y=False)
        self.overview.setToolTip("ホイール: 時間軸のみ拡大／縮小 · 範囲をドラッグ: メイン波形の表示時間を移動")
        self.overview.hideAxis("left")
        self.region = pg.LinearRegionItem(values=(0, 1), brush=(80, 160, 220, 35))
        self.overview.addItem(self.region, ignoreBounds=True)
        self.region.sigRegionChanged.connect(self.region_changed)
        self.plot.getViewBox().sigXRangeChanged.connect(self.range_changed)
        layout.addWidget(self.overview)
        self.table = W.QTableWidget(0, 6 + len(METRICS))
        self.table.setHorizontalHeaderLabels(["CH / 単位", "t(A)", "値 A", "t(B)", "値 B", "Δ(B−A)",
                                               *[m.title for m in METRICS]])
        for index, metric in enumerate(METRICS, 6):
            self.table.setColumnHidden(index, not self.measurement_actions[metric.key].isChecked())
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.Interactive)
        self.table.horizontalHeader().setMinimumSectionSize(90)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(140)
        layout.addWidget(self.table, 1)
        self.hover_label = W.QLabel("マウス位置: —")
        self.hover_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self.hover_label)
        self.mouse_proxy = pg.SignalProxy(self.plot.scene().sigMouseMoved, rateLimit=25, slot=self.mouse_moved)
        self.mode_tabs = W.QTabWidget()
        self.mode_tabs.addTab(center, "波形・解析")
        self.screen_panel = ScreenPanel()
        self.screen_panel.requested.connect(self.read_screen)
        self.screen_panel.auto_requested.connect(self.set_screen_auto)
        self.screen_panel.connection_changed.connect(self.invalidate_screen)
        self.mode_tabs.addTab(self.screen_panel, "本体画面")
        self.mode_tabs.currentChanged.connect(self.mode_changed)
        self.setCentralWidget(self.mode_tabs)
        self.update_screen_target()
        self.resizeDocks([self.sidebar_dock], [310], QtCore.Qt.Horizontal)
        self.wheel_axis_combo.currentIndexChanged.connect(self.set_wheel_axis)
        self.set_wheel_axis()
        self.antialias_checkbox.toggled.connect(self.set_antialias)
        self.set_antialias(self.antialias_checkbox.isChecked())

    def set_antialias(self, enabled):
        self.settings.setValue("antialias", enabled)
        pg.setConfigOption("antialias", enabled)
        for plot in self.findChildren(pg.PlotWidget):
            plot.setRenderHint(QtGui.QPainter.Antialiasing, enabled)
            for curve in plot.listDataItems():
                curve.setData(curve.xData, curve.yData, antialias=enabled)

    def set_wheel_axis(self, *args):
        axis = self.wheel_axis_combo.currentData()
        self.plot.getViewBox().wheel_axis = 0 if axis == "x" else 1
        self.settings.setValue("wheel_axis", axis)

    def set_interpolation(self, *args):
        mode = self.interpolation_combo.currentData()
        self.settings.setValue("interpolation", mode)
        for item in self.curves:
            item.set_interpolation(mode)
        if hasattr(self, "overview"):
            for item in self.overview.listDataItems():
                item.set_interpolation(mode)

    def zoom_from_overview(self, factor, anchor):
        lo, hi = self.plot.viewRange()[0]
        x_range = [anchor + (value-anchor)*factor for value in (lo, hi)]
        if np.all(np.isfinite(x_range)) and x_range[1] > x_range[0]:
            self.plot.setRange(xRange=x_range, yRange=self.plot.viewRange()[1], padding=0)
            self.mark_dirty()

    def apply_theme(self, name):
        name = name if name in THEMES else "dark"
        colors = THEMES[name]
        configure_application(W.QApplication.instance(), name)
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(name))
        self.theme_combo.blockSignals(False)
        self.settings.setValue("theme", name)
        self.heading.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {colors['accent']}; padding: 8px 0;")
        colors = THEMES['dark'] if self.dark_plot.isChecked() else colors
        for plot in self.findChildren(pg.PlotWidget):
            plot.setBackground(colors["base"])
            for side in ("left", "bottom"):
                plot.getAxis(side).setPen(colors["muted"])
                plot.getAxis(side).setTextPen(colors["muted"])
            if plot.plotItem.legend:
                plot.plotItem.legend.setLabelTextColor(colors["text"])
                for _, label in plot.plotItem.legend.items:
                    label.setText(label.text, color=colors["text"])
        for cursor, color in ((self.cursor_a, "#d09300"), (self.cursor_b, "#208ae5")):
            cursor.setPen(pg.mkPen(color, width=1.5, style=QtCore.Qt.DashLine))
            cursor.label.setColor(color)
        self.plot.setTitle(self.file_label.text(), color=colors["text"], size="12pt")

    def set_dark_plot(self, enabled):
        self.settings.setValue('dark_plot', enabled)
        self.apply_theme(self.theme_combo.currentData())

    def error(self, message):
        W.QMessageBox.warning(self, "操作を完了できませんでした", str(message))

    def mark_dirty(self, *args):
        if self.traces:
            self.dirty = True

    def confirm_replace(self):
        if not self.dirty:
            return True
        answer = W.QMessageBox.question(self, "波形の保存", "現在の波形・設定を保存しますか？",
            W.QMessageBox.Save | W.QMessageBox.Discard | W.QMessageBox.Cancel, W.QMessageBox.Save)
        if answer == W.QMessageBox.Cancel:
            return False
        if answer == W.QMessageBox.Save:
            return self.save_dialog()
        return True

    def open_dialog(self):
        path, _ = W.QFileDialog.getOpenFileName(self, "波形を開く", str(self.settings.value("directory", "")),
            "波形 (*.WVF *.wvf *.HDR *.hdr *.csv *.CSV *.npz *.json);;すべて (*)")
        if path:
            self.open_path(path)

    def open_path(self, path):
        self.mode_tabs.setCurrentIndex(0)
        if self.live_enabled:
            self.set_live(False)
        if not self.confirm_replace():
            return
        try:
            traces, view = load_file(path)
            self.set_traces(traces, Path(path).name, view)
            self.settings.setValue("directory", str(Path(path).parent))
            self.dirty = False
        except Exception as exc:
            self.error(exc)

    def set_traces(self, traces, title, view=None):
        view, self.view_recovered = restore_view(traces, view)
        self.traces = traces
        self.file_label.setText(title)
        plot_theme = 'dark' if self.dark_plot.isChecked() else self.theme_combo.currentData()
        self.plot.setTitle(title, color=THEMES[plot_theme]["text"], size="12pt")
        self.rebuild_channels()
        self.redraw()
        self.fit()
        self.place_cursors()
        if view:
            interpolation_index = self.interpolation_combo.findData(view.get("interpolation", ""))
            if interpolation_index >= 0:
                self.interpolation_combo.setCurrentIndex(interpolation_index)
            if "theme" in view:
                self.apply_theme(view["theme"])
            if "x_range" in view:
                self.plot.setXRange(*view["x_range"], padding=0)
            if "y_range" in view:
                self.plot.setYRange(*view["y_range"], padding=0)
            for key, cursor in (("cursor_a", self.cursor_a), ("cursor_b", self.cursor_b)):
                if key in view:
                    cursor.setValue(view[key])
        self.update_readouts()
        message = f"{title} · {len(traces)} CH · " + ", ".join(f"{t.name}: {len(t.x):,}点" for t in traces)
        if self.view_recovered:
            message += " · 保存表示範囲が波形に合わないため全体表示へ補正しました"
        self.statusBar().showMessage(message)

    def request_live(self, enabled):
        if enabled or not self.live_enabled:
            self.set_live(enabled)
            return
        self._disconnect_requested = True
        self._live_timer.stop()
        self.instrument_panel.live_button.setEnabled(False)
        self.statusBar().showMessage("最後の記録を全点取得してから接続を解除します…")
        if self.worker is None:
            self.network("DISCONNECT_CAPTURE", {"generation": self._live_generation})

    def set_live(self, enabled):
        if enabled and not self.live_enabled and not self.confirm_replace():
            enabled = False
        if enabled:
            self.mode_tabs.setCurrentIndex(0)
        if enabled != self.live_enabled:
            self._live_generation += 1
        self.live_enabled = enabled
        if not enabled:
            self._disconnect_requested = False
            self.instrument_panel.live_button.setEnabled(True)
        self.instrument_panel.set_live_state(enabled)
        self.math_group.setEnabled(not enabled)
        self._live_timer.stop()
        if enabled:
            self._live_first_frame = True
            self._stopped_frame_valid = False
            self._live_count = 0
            self._live_started = time.monotonic()
            self._live_timer.start(100)
        else:
            if self.worker is None:
                self.close_live_device()
            self.statusBar().showMessage("実機との接続を解除しました。最後の波形を表示しています。")

    def poll_live(self):
        if not self.live_enabled:
            return
        panel = self.instrument_panel
        if self.worker or panel._pending or panel._refresh_requested or panel._lcd_pending is not None:
            self._live_timer.start(100)
            return
        self.network("LIVE", {"generation": self._live_generation,
                              "allow_pause": self.instrument_panel.live_mode.currentData(),
                              "capture_stopped": not self._stopped_frame_valid})

    def toggle_instrument(self):
        if self.instrument_panel.running is None:
            self.statusBar().showMessage("実機に接続して状態を読み込んでからRUN/STOPを操作してください。")
            return
        self.network("TOGGLE_RUN", {"channel": self.instrument_panel.channel.currentData()})

    def queue_run_toggle(self):
        baseline = self._run_in_flight_target if self._run_in_flight else self.instrument_panel.running
        if baseline is None:
            return
        current = self._pending_run_target if self._pending_run_toggle else baseline
        self._pending_run_target = not current
        self._pending_run_toggle = self._pending_run_target != baseline
        self.instrument_panel.set_run_pending(self._pending_run_toggle or self._run_in_flight)
        self._live_timer.stop()
        if self.worker is None:
            self.dispatch_run_toggle()

    def dispatch_run_toggle(self):
        if self.worker is not None or not self._pending_run_toggle:
            return
        self._pending_run_toggle = False
        self._run_in_flight = True
        self._run_in_flight_target = self._pending_run_target
        self._stopped_frame_valid = False
        self.instrument_panel.set_run_pending(True)
        self.network("RUN_TOGGLE", {"channel": self.instrument_panel.channel.currentData(),
                                    "running": self._run_in_flight_target})

    def update_live_frame(self, traces, host):
        previous = {t.name: t for t in self.traces}
        for trace in traces:
            old = previous.get(trace.name)
            if old is not None:
                trace.color, trace.visible = old.color, old.visible
        title = f"DL1640 Live @ {host}"
        same = [t.name for t in self.traces] == [t.name for t in traces]
        if self._live_first_frame or not same:
            view = None if self._live_first_frame else self.view_state()
            self.set_traces(traces, title, view)
            self._live_first_frame = False
        else:
            self.traces = traces
            self._stats_cache.clear()
            for trace in traces:
                label = self.channel_info_labels.get(trace.name)
                if label is not None:
                    text = self.channel_info_text(trace)
                    if label.text() != text:
                        label.setText(text)
                        self.set_channel_info_tooltip(label, text)
            visible = [t for t in traces if t.visible]
            for curve, overview, trace in zip(self.curves, self.overview.listDataItems(), visible):
                curve.setData(trace.x, trace.y)
                overview.setData(trace.x, trace.y)
            bounds = waveform_bounds(traces)
            if bounds:
                self.overview.setRange(xRange=bounds[0], yRange=bounds[1], padding=.04)
            _, recover = restore_view(traces, self.view_state())
            if recover:
                self.fit()
                self.place_cursors()
            self.schedule_readouts()
        self.dirty = True
        self._live_count += 1
        elapsed = max(time.monotonic()-self._live_started, .001)
        self.statusBar().showMessage(f"ライブ更新 · {self._live_count}フレーム · 平均 {self._live_count/elapsed:.2f} fps · {host}")

    def rebuild_channels(self):
        while self.channel_layout.count():
            item = self.channel_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        selected_source = self.math_source.currentText()
        self.math_source.blockSignals(True)
        self.math_source.clear()
        self.channel_info_labels = {}
        for trace in self.traces:
            row = W.QWidget()
            outer = W.QVBoxLayout(row)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(2)
            layout = W.QHBoxLayout()
            outer.addLayout(layout)
            layout.setContentsMargins(0, 0, 0, 0)
            check = W.QCheckBox(f"{trace.name}  [{trace.unit}]")
            check.setChecked(trace.visible)
            check.toggled.connect(lambda on, t=trace: self.toggle_trace(t, on))
            layout.addWidget(check, 1)
            color = button("色", lambda checked=False, t=trace: self.change_color(t))
            color.setStyleSheet(f"color: {trace.color}; font-weight: bold;")
            layout.addWidget(color)
            remove = button("×", lambda checked=False, t=trace: self.remove_trace(t))
            remove.setMaximumWidth(32)
            remove.setToolTip("この波形を削除")
            layout.addWidget(remove)
            self.channel_layout.addWidget(row)
            info = W.QLabel(self.channel_info_text(trace))
            info.setWordWrap(True)
            info.setTextFormat(QtCore.Qt.PlainText)
            info.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            info.setProperty("muted", True)
            info.setStyleSheet('font-size: 11px;')
            self.set_channel_info_tooltip(info, info.text())
            outer.addWidget(info)
            self.channel_info_labels[trace.name] = info
            self.math_source.addItem(trace.name)
        source_index = self.math_source.findText(selected_source)
        if source_index >= 0:
            self.math_source.setCurrentIndex(source_index)
        self.math_source.blockSignals(False)

    def set_channel_info_tooltip(self, label, text):
        label.setToolTip(text + '\n\nT/div・V/div・Offsetは取得時に照会した本体設定です。'
            '\nSTOP中の設定変更後は、記録当時の条件と異なる場合があります。')

    def channel_info_text(self, trace):
        fs = trace.metadata.get("sample_rate")
        if not isinstance(fs, (int, float)) or not np.isfinite(fs) or fs <= 0:
            intervals = np.diff(trace.x)
            dt = intervals[0]
            fs = 1 / dt if np.allclose(intervals, dt, rtol=1e-5, atol=abs(dt)*1e-8) else None
        timing = (f"Fs {fmt(fs, 'Sa/s')} | dt {fmt(1/fs, 's')}" if fs else "Fs N/A | dt non-uniform")
        text = f"{len(trace.x):,} pts | {timing}"
        settings = []
        for key, label, unit in (("time_div", "T/div", "s"), ("vertical_div", f"{trace.unit}/div", trace.unit),
                                 ("vertical_offset", "Offset", trace.unit)):
            value = trace.metadata.get(key)
            if isinstance(value, (int, float)) and np.isfinite(value):
                settings.append(f"{label} {fmt(value, unit)}")
            elif key != 'vertical_offset':
                settings.append(f"{label} N/A")
        return text + '\n' + ' | '.join(settings) + f"\nSpan {fmt(trace.x[-1] - trace.x[0], 's')}"

    def toggle_trace(self, trace, visible):
        trace = next((current for current in self.traces if current.name == trace.name), trace)
        trace.visible = visible
        self.mark_dirty()
        self.redraw()

    def change_color(self, trace):
        trace = next((current for current in self.traces if current.name == trace.name), trace)
        color = W.QColorDialog.getColor(QtGui.QColor(trace.color), self, f"{trace.name} の色")
        if color.isValid():
            trace.color = color.name()
            self.mark_dirty()
            self.rebuild_channels()
            self.redraw()

    def remove_trace(self, trace):
        trace = next((current for current in self.traces if current.name == trace.name), trace)
        self.traces = [t for t in self.traces if t is not trace]
        self.dirty = True
        self.rebuild_channels()
        self.redraw()

    def redraw(self):
        self._stats_cache.clear()
        for item in self.curves:
            self.plot.removeItem(item)
        self.curves = []
        for item in list(self.overview.listDataItems()):
            self.overview.removeItem(item)
        self.plot.plotItem.legend.clear()
        for t in self.traces:
            if not t.visible:
                continue
            curve = WaveformPlotItem(t.x, t.y, pen=pg.mkPen(t.color, width=1.5), name=t.name, connect="finite",
                                   antialias=self.antialias_checkbox.isChecked(), autoDownsampleFactor=1.)
            self.plot.addItem(curve)
            curve.set_interpolation(self.interpolation_combo.currentData())
            self.curves.append(curve)
            overview_curve = WaveformPlotItem(t.x, t.y, pen=t.color, connect="finite",
                                               antialias=self.antialias_checkbox.isChecked(), autoDownsampleFactor=1.)
            self.overview.addItem(overview_curve)
            overview_curve.set_interpolation(self.interpolation_combo.currentData())
            overview_curve.setDownsampling(auto=True, method="peak")
            overview_curve.curve.setCacheMode(W.QGraphicsItem.DeviceCoordinateCache)
        self.update_readouts()
        self.table.resizeColumnsToContents()

    def fit(self):
        # Use original samples: extreme prior axes can leave the decimated curve
        # empty, so autoRange() on that curve cannot recover the actual bounds.
        bounds = waveform_bounds(self.traces)
        if bounds:
            for plot in (self.plot, self.overview):
                plot.setRange(xRange=bounds[0], yRange=bounds[1], padding=.04)

    def place_cursors(self):
        lo, hi = self.plot.viewRange()[0]
        self.cursor_a.setValue(lo + (hi-lo) * 0.35)
        self.cursor_b.setValue(lo + (hi-lo) * 0.65)

    def zoom_cursors(self):
        lo, hi = sorted((self.cursor_a.value(), self.cursor_b.value()))
        if hi > lo:
            self.plot.setXRange(lo, hi, padding=0)

    def region_changed(self):
        self.plot.setXRange(*self.region.getRegion(), padding=0)

    def range_changed(self, *args):
        self.region.blockSignals(True)
        self.region.setRegion(self.plot.viewRange()[0])
        self.region.blockSignals(False)
        self.schedule_readouts()

    def schedule_readouts(self, *args):
        self.update_cursor_summary()
        if not self._readout_timer.isActive():
            self._readout_timer.start()

    def update_cursor_summary(self):
        if not hasattr(self, "cursor_label"):
            return
        a, b = self.cursor_a.value(), self.cursor_b.value()
        delta = b-a
        self.cursor_label.setText(f"A = {fmt(a, 's')}    B = {fmt(b, 's')}    Δt = {fmt(delta, 's')}    "
                                  f"1/|Δt| = {fmt(1/abs(delta), 'Hz') if delta else '—'}")

    def measurement_selection_changed(self, *args):
        selected = [key for key, action in self.measurement_actions.items() if action.isChecked()]
        self.settings.setValue("measurement_items", selected)
        if hasattr(self, "table"):
            for index, metric in enumerate(METRICS, 6):
                self.table.setColumnHidden(index, metric.key not in selected)
            self._stats_cache.clear()
            self.schedule_readouts()

    def update_readouts(self, *args):
        if not hasattr(self, "table"):
            return
        self._readout_timer.stop()
        a, b = self.cursor_a.value(), self.cursor_b.value()
        self.update_cursor_summary()
        self.table.setRowCount(len(self.traces))
        lo, hi = self.plot.viewRange()[0]
        selected = tuple(key for key, action in self.measurement_actions.items() if action.isChecked())
        if self.measure_ab.isChecked():
            lo, hi = sorted((a, b))
        for row, t in enumerate(self.traces):
            ta, ya = t.nearest(a)
            tb, yb = t.nearest(b)
            start, end = (np.searchsorted(t.x, lo), np.searchsorted(t.x, hi, side="right")) if self.measure_ab.isChecked() or self.visible_stats.isChecked() else (0, len(t.y))
            cached = self._stats_cache.get(id(t))
            if cached is not None and cached[:3] == (start, end, selected):
                stats = cached[3]
            else:
                stats = measure(t.x[start:end], t.y[start:end], selected)
                self._stats_cache[id(t)] = (start, end, selected, stats)
            values = [f"{t.name} [{t.unit}]", fmt(ta, "s"), fmt(ya, t.unit), fmt(tb, "s"),
                      fmt(yb, t.unit), fmt(yb-ya, t.unit)] + [
                          fmt(stats.get(m.key, np.nan), t.unit if m.unit == 'signal' else m.unit) for m in METRICS]
            for col, text in enumerate(values):
                item = self.table.item(row, col)
                if item is None:
                    item = W.QTableWidgetItem(text)
                    self.table.setItem(row, col, item)
                elif item.text() != text:
                    item.setText(text)
                item.setToolTip(text)
                if col == 0:
                    item.setForeground(QtGui.QColor(t.color))

    def mouse_moved(self, event):
        pos = event[0]
        if not self.plot.sceneBoundingRect().contains(pos):
            return
        point = self.plot.getViewBox().mapSceneToView(pos)
        values = []
        for t in self.traces:
            if t.visible:
                tx, y = t.nearest(point.x())
                values.append(f"{t.name}: {fmt(y, t.unit)} @ {fmt(tx, 's')}")
        self.hover_label.setText("最寄りサンプル  ·  " + "   |   ".join(values))

    def next_math_name(self):
        i = 1
        while any(t.name == f"MATH{i}" for t in self.traces):
            i += 1
        return f"MATH{i}"

    def append_math(self, trace):
        x_range = self.plot.viewRange()[0]
        self.traces.append(trace)
        self.mark_dirty()
        self.rebuild_channels()
        self.redraw()
        self.fit()
        self.plot.setXRange(*x_range, padding=0)
        self.statusBar().showMessage(f"{trace.name} を追加しました。演算結果は追加時点の波形です。")

    def add_expression(self):
        try:
            self.append_math(expression_trace(self.expression.text(), self.traces, self.next_math_name()))
        except Exception as exc:
            self.error(exc)

    def selected_trace(self):
        name = self.math_source.currentText()
        return next((t for t in self.traces if t.name == name), None)

    def add_transform(self):
        trace = self.selected_trace()
        if trace:
            try:
                self.append_math(transform(trace, self.math_operation.currentText(), self.next_math_name(), self.smooth_window.value()))
            except Exception as exc:
                self.error(exc)

    def show_protocol(self):
        if not self.traces:
            self.statusBar().showMessage("波形を取得または読み込んでください。")
            return
        if self.live_enabled and self.instrument_panel.running:
            self.statusBar().showMessage("実機をSTOPしてからプロトコル解析を開始してください。")
            return
        from yokogawa_tool.gui.protocol_panel import ProtocolDialog
        dialog = ProtocolDialog(self.traces, self.settings, self)
        self.windows.append(dialog)
        dialog.show()

    def show_fft(self):
        trace = self.selected_trace()
        if not trace:
            return
        try:
            frequency, amplitude = spectrum(trace)
            window = W.QDialog(self)
            window.setWindowTitle(f"FFT · {trace.name} · Hann窓 / 片側ピーク振幅")
            window.resize(950, 550)
            layout = W.QVBoxLayout(window)
            plot = pg.PlotWidget()
            plot.setLabel("bottom", "Frequency", units="Hz")
            plot.setLabel("left", "Amplitude", units=trace.unit)
            plot.showGrid(x=True, y=True, alpha=0.2)
            plot.plot(frequency, amplitude, pen=trace.color)
            layout.addWidget(plot)
            label = W.QLabel("波形全体を解析 · Hann窓のコヒーレントゲイン補正済み · DCは除去しません")
            layout.addWidget(label)
            self.windows.append(window)
            window.show()
        except Exception as exc:
            self.error(exc)

    def view_state(self):
        xr, yr = self.plot.viewRange()
        return {"x_range": xr, "y_range": yr, "cursor_a": self.cursor_a.value(), "cursor_b": self.cursor_b.value(),
                "theme": self.theme_combo.currentData(), "interpolation": self.interpolation_combo.currentData()}

    def save_dialog(self):
        if not self.traces:
            return False
        path, selected_filter = W.QFileDialog.getSaveFileName(self, "波形と設定を保存", "waveform.scope.npz",
            "セッション (*.scope.npz);;JSONセッション (*.scope.json)")
        if not path:
            return False
        if "JSON" in selected_filter and path.lower().endswith(".npz"):
            path = path[:-len(".scope.npz")] + ".scope.json" if path.lower().endswith(".scope.npz") else str(Path(path).with_suffix(".scope.json"))
        if not path.lower().endswith((".npz", ".json")):
            path += ".scope.json" if "JSON" in selected_filter else ".scope.npz"
        try:
            save_session(path, self.traces, self.view_state())
            self.dirty = False
            self.statusBar().showMessage(f"保存しました: {path}")
            return True
        except Exception as exc:
            self.error(exc)
            return False

    def csv_dialog(self):
        if not self.traces:
            return
        path, _ = W.QFileDialog.getSaveFileName(self, "全CHをCSVに出力", "waveform.csv", "CSV (*.csv)")
        if path:
            try:
                export_csv(path, self.traces)
                self.statusBar().showMessage(f"CSVを保存しました: {path}")
            except Exception as exc:
                self.error(exc)

    def wvf_dialog(self):
        if not self.traces:
            return
        path, _ = W.QFileDialog.getSaveFileName(self, "波形をWVF/HDRに出力（PC解析用）", "waveform.WVF",
                                               "Yokogawa波形 (*.WVF *.wvf)",
                                               options=W.QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return
        try:
            targets = wvf_paths(path)
            existing = [str(p) for p in targets if p.exists()]
            if existing and W.QMessageBox.question(self, "WVF/HDRの上書き",
                    "次のファイルを上書きしますか？\n" + "\n".join(existing),
                    W.QMessageBox.StandardButton.Yes | W.QMessageBox.StandardButton.No,
                    W.QMessageBox.StandardButton.No) != W.QMessageBox.StandardButton.Yes:
                return
            wave, header = export_wvf(path, self.traces)
            self.statusBar().showMessage(f"WVF/HDRを保存しました: {wave} / {header}（PC解析用）")
        except Exception as exc:
            self.error(exc)

    def image_dialog(self):
        if self.mode_tabs.currentIndex() == 1:
            self.screen_panel.save_dialog()
            return
        path, _ = W.QFileDialog.getSaveFileName(self, "波形表示を画像に保存", "waveform.png", "PNG (*.png)")
        if path:
            from pyqtgraph.exporters import ImageExporter
            try:
                ImageExporter(self.plot.plotItem).export(path)
                self.statusBar().showMessage(f"画像を保存しました: {path}")
            except Exception as exc:
                self.error(exc)

    def close_live_device(self):
        if self._live_device is not None:
            _, context, _ = self._live_device
            self._live_device = None
            context.__exit__(None, None, None)
            message = getattr(context, "display_restore_error", None)
            if message:
                self.display_restore_failed.emit(message)

    @QtCore.Slot(str)
    def report_display_restore_failure(self, message):
        self.network_label.setText(message)
        self.network_label.setToolTip(message)
        self.statusBar().showMessage(message, 20000)

    def update_screen_target(self):
        self.screen_panel.target.setText(f"接続先: {self.host.text().strip()}:{self.screen_panel.port.value()}"
                                         " · IP・認証は左の「実機操作」で変更します")

    def invalidate_screen(self):
        self.set_screen_auto(False)
        self._screen_generation += 1
        self.screen_panel.clear_image()
        self.update_screen_target()

    def instrument_invalidated(self):
        self._pending_run_toggle = False
        self._run_in_flight = False
        self._run_in_flight_target = None
        self.instrument_panel.set_run_pending(False)
        if self.live_enabled:
            self.set_live(False)
        self.invalidate_screen()

    def mode_changed(self, index):
        analysis = index == 0
        for name in ("セッション保存", "CSV出力", "WVF/HDR出力"):
            self.file_actions[name].setEnabled(analysis)
        self.wheel_axis_combo.setEnabled(analysis)
        self.rect_mode.setEnabled(analysis)
        self.sidebar_tabs.widget(0).setEnabled(analysis)
        if index == 1:
            if self.live_enabled:
                self.set_live(False)
        else:
            self.set_screen_auto(False)
            self._screen_generation += 1
            if self._worker_action == "SCREEN":
                self.screen_panel.status.setText("本体画面の更新を停止しました。")

    def fit_current_view(self):
        if self.mode_tabs.currentIndex() == 1:
            self.screen_panel.view.fit_image()
        else:
            self.fit()

    def set_screen_auto(self, enabled):
        if enabled:
            self.mode_tabs.setCurrentIndex(1)
        if enabled != self.screen_enabled:
            self._screen_generation += 1
            if not enabled:
                self.screen_panel.status.setText("本体画面の自動更新を終了しました。")
        self.screen_enabled = enabled
        self.screen_panel.set_auto_state(enabled)
        self._screen_timer.stop()
        if enabled:
            self._screen_timer.start(0)

    def poll_screen(self):
        if not self.screen_enabled or self.mode_tabs.currentIndex() != 1:
            return
        panel = self.instrument_panel
        if self.worker is not None or panel._pending or panel._refresh_requested:
            self._screen_timer.start(100)
            return
        self.read_screen()

    def read_screen(self):
        if self.worker is not None:
            return
        self.mode_tabs.setCurrentIndex(1)
        self.network("SCREEN", {"generation": self._screen_generation,
                                "http_port": self.screen_panel.port.value()})

    @contextmanager
    def device_connection(self, config, persistent):
        # Called only by the single network worker. Idle cleanup runs on the GUI.
        if not persistent:
            self.close_live_device()
            with DL1640(**config) as scope:
                yield scope
            return
        if self._live_device is not None and self._live_device[0] != config:
            self.close_live_device()
        if self._live_device is None:
            context = DL1640(**config)
            scope = context.__enter__()
            self._live_device = (dict(config), context, scope)
        try:
            yield self._live_device[2]
        except Exception:
            self.close_live_device()
            raise

    def network(self, action, values=None):
        if action == "TOGGLE_RUN":
            self.queue_run_toggle()
            return
        if action == "CAPTURE":
            self.mode_tabs.setCurrentIndex(0)
        if action == "CAPTURE" and self.live_enabled:
            self.set_live(False)
        if self.worker is not None:
            return
        if action == "CAPTURE" and not self.confirm_replace():
            return
        host = self.host.text().strip()
        if not host:
            if self.live_enabled:
                self.set_live(False)
            if action == "SCREEN":
                self.set_screen_auto(False)
                self.screen_panel.status.setText("IPアドレスを入力してください。")
                return
            self.error("IPアドレスを入力してください。")
            return
        config = dict(host=host, port=self.port.value(), username=self.username.text(), password=self.password.text())
        values = dict(values or {})
        blank_display = self.instrument_panel.blank_display.isChecked()
        persistent = self.live_enabled and action != "LOCAL"
        self._live_timer.stop()
        self._screen_timer.stop()
        self.settings.setValue("host", host)
        self.settings.setValue("username", config["username"])

        def work():
            if action == "SCREEN":
                # HTTP image generation competes with a persistent control session.
                self.close_live_device()
                result = fetch_screen(host, port=values["http_port"],
                                      username=config["username"], password=config["password"])
                result["generation"] = values["generation"]
                return result
            with self.device_connection(config, persistent) as scope:
                display_manager = getattr(scope, "set_display_blanked", None)
                if display_manager is not None and action not in ("LOCAL", "READ_LCD", "LCD"):
                    display_manager(blank_display)
                if action in ('LCD', 'READ_LCD'):
                    return scope.configure_lcd(**values)
                if action == "ID":
                    return scope.identify()
                if action == "CAPTURE":
                    return scope.capture()
                if action in ("LIVE", "DISCONNECT_CAPTURE"):
                    result = scope.capture_live(allow_pause=values.get("allow_pause", True),
                                                capture_stopped=values.get("capture_stopped", True))
                    result["generation"] = values["generation"]
                    return result
                if action == "READ_SETTINGS":
                    return scope.read_settings(values.get("channel", 1))
                if action.startswith("APPLY_"):
                    fields = values.pop("_fields", None)
                    return scope.apply_settings(action[6:].lower(), values, fields=fields)
                if action == "RUN_TOGGLE":
                    return scope.set_running(values["running"], values.get("channel", 1))
                if action == "AUTO_SETUP":
                    scope.control(action)
                    return scope.read_settings(values.get("channel", 1))
                message = scope.control(action)
                return scope.read_settings(values.get("channel", 1)) if action == "SINGLE" else message

        if action == "SCREEN":
            self.screen_panel.status.setText(f"{host} · 本体画面を取得中…（実機の応答には数秒かかります）")
        elif action != "LIVE":
            self.network_label.setText(f"{host} · {action} 実行中…")
        self.instrument_panel.set_busy(True)
        self.screen_panel.set_busy(True)
        self._network_started = time.monotonic()
        self._worker_action = action
        self.worker = Worker(work, self)
        self.worker.result.connect(lambda result: self.network_result(action, host, result))
        self.worker.failed.connect(lambda message: self.network_failed(message, action, values.get("generation")))
        self.worker.finished.connect(self.network_finished)
        self.worker.start()

    def network_result(self, action, host, result):
        if action == "SCREEN":
            if result["generation"] != self._screen_generation or self.mode_tabs.currentIndex() != 1:
                return
            try:
                self.screen_panel.set_frame(result["png"], host, result["seconds"])
            except ValueError as exc:
                self.network_failed(str(exc), action, result["generation"])
        elif action in ('LCD', 'READ_LCD'):
            self.instrument_panel.set_lcd_state(result)
            self.statusBar().showMessage('本体LCDの状態を読み込みました。')
        elif action in ("LIVE", "DISCONNECT_CAPTURE"):
            if result["generation"] != self._live_generation or not self.live_enabled:
                return
            if action == "DISCONNECT_CAPTURE":
                self._disconnect_capture_waiting = result['waiting']
                previous = {t.name: t for t in self.traces}
                incoming = result['traces']
                if incoming and all(t.name in previous and
                        np.array_equal(t.x, previous[t.name].x) and
                        np.array_equal(t.y, previous[t.name].y, equal_nan=True) for t in incoming):
                    names = {t.name for t in incoming}
                    incoming.extend(t for t in self.traces if t.name not in names and
                                    ('expression' in t.metadata or 'operation' in t.metadata))
            self.instrument_panel.running = result["running"]
            if result["running"]:
                self._stopped_frame_valid = False
            self.instrument_panel.update_run_button()
            self.run_action.setEnabled(True)
            if result["waiting"]:
                if result.get("reason") == "stopped":
                    self.network_label.setText("実機は停止中 · 波形を保持しています · SpaceでRUN")
                else:
                    self.network_label.setText("単発取得の完了待ち" if result.get("reason") != "running"
                                               else "測定を中断せず本体のSTOPを待っています")
            else:
                self.instrument_panel.update_waveform_info(result['traces'])
                self.update_live_frame(result["traces"], host)
                self._stopped_frame_valid = not result["running"]
                pause = result.get("pause_seconds", 0) * 1000
                self.network_label.setText(f"ライブ更新 · {self._live_count}フレーム · "
                                           + (f"RUN復帰済み · 停止・復帰処理 {pause:.0f} ms" if result['running'] else "実機は停止中"))
            self.math_group.setEnabled(not result["running"] and self._stopped_frame_valid)
        elif action == "CAPTURE":
            self.instrument_panel.update_waveform_info(result)
            self.set_traces(result, f"DL1640 @ {host}")
            self.dirty = True
            self.network_label.setText(f"取得完了 · {len(result)} CH")
        elif isinstance(result, dict):
            self.instrument_panel.update_settings(result)
            if result["running"] or action in ("RUN_TOGGLE", "SINGLE", "AUTO_SETUP") or action.startswith("APPLY_"):
                self._stopped_frame_valid = False
            if self.live_enabled:
                self.math_group.setEnabled(not result["running"] and self._stopped_frame_valid)
            if action.startswith("APPLY_"):
                self.network_label.setText(self.network_label.text() + "\n設定を適用し、本体の実値を読込済み")
        else:
            if action == "LOCAL":
                self.instrument_panel.invalidate()
            self.network_label.setText(str(result))
        if isinstance(result, dict) and result.get("warnings"):
            message = "操作前から残っていた実機エラー: " + " / ".join(result["warnings"])
            self.statusBar().showMessage(message, 15000)
            self.network_label.setToolTip(message)

    def network_failed(self, message, action=None, generation=None):
        if action == "SCREEN":
            if generation == self._screen_generation:
                self.set_screen_auto(False)
                self.screen_panel.status.setText(f"本体画面の取得に失敗しました: {message}")
            return
        if self.live_enabled:
            self.set_live(False)
        self.network_label.setText("接続 / 操作に失敗しました")
        self.instrument_panel.invalidate()
        self.error(message)

    def network_finished(self):
        previous = self.worker
        previous_action = self._worker_action
        self.worker = None
        self._worker_action = None
        if previous:
            previous.deleteLater()
        if previous_action == "RUN_TOGGLE":
            self._run_in_flight = False
            self._run_in_flight_target = None
        self.instrument_panel.set_run_pending(self._pending_run_toggle or self._run_in_flight)
        if self._pending_run_toggle:
            self.dispatch_run_toggle()
            return
        self.instrument_panel.set_busy(False)
        self.screen_panel.set_busy(False)
        if self._disconnect_requested:
            if previous_action == "DISCONNECT_CAPTURE":
                waiting = self._disconnect_capture_waiting
                self.set_live(False)
                self.statusBar().showMessage("単発取得中のため前回の波形を保持して切断しました。" if waiting else
                                             "最後の記録を全点取得し、接続を解除しました。")
            else:
                self.network("DISCONNECT_CAPTURE", {"generation": self._live_generation})
            return
        if self.live_enabled:
            # Target request-to-request spacing; transfer time is already elapsed.
            remaining = self.instrument_panel.live_interval.value() - (time.monotonic() - self._network_started)*1000
            self._live_timer.start(max(0, round(remaining)))
        else:
            self.close_live_device()
        if self.screen_enabled:
            remaining = self.screen_panel.interval.value()*1000 - (time.monotonic() - self._network_started)*1000
            self._screen_timer.start(max(0, round(remaining)))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            self.open_path(urls[0].toLocalFile())

    def closeEvent(self, event):
        if any(getattr(window, 'worker', None) is not None and window.worker.isRunning() for window in self.windows):
            self.statusBar().showMessage("プロトコル解析が終了してから終了してください。")
            event.ignore()
            return
        self.set_screen_auto(False)
        if self.live_enabled:
            self.set_live(False)
        if self.instrument_panel._pending:
            self.instrument_panel.sync_timer.start(0)
            self.statusBar().showMessage("設定の自動反映が完了してから終了してください。")
            event.ignore()
            return
        if self.worker and self.worker.isRunning():
            self.statusBar().showMessage("通信処理が完了してから終了してください。")
            event.ignore()
        elif self.confirm_replace():
            event.accept()
        else:
            event.ignore()

    def help_dialog(self):
        W.QMessageBox.information(self, "使い方", "ファイルを開く: WVFと同名HDRを同じフォルダに置いて選択。\n"
            "ホイール: ツールバーで『横のみ／縦のみ』を選択（次回起動時も保持）。\n"
            "ドラッグ: 移動 / Home: 全体表示。\n"
            "下段Overviewのホイールは常に時間軸のみ拡大・縮小します。\n"
            "『範囲をドラッグして拡大』または下段Overviewで表示範囲を指定。\n"
            "『左パネル』またはCtrl+Bで操作パネルを折り畳み・再表示できます。\n"
            "『波形・解析』のアンチエイリアスで描画を滑らかにできます（測定データは不変）。\n"
            "『実機操作』タブは設定を自動読込。±ボタンや設定変更は自動送信し、実値を再取得します。\n"
            "レコード長は本体対応値の選択式です。通常は最大8M、高分解能時は最大4Mです。\n"
            "A/Bの縦線を動かすと最寄りサンプル時刻・値と差分を確認できます。\n"
            "測定表は表示中の時間範囲、または波形全体を集計します。\n"
            "『Measure · 測定項目』で21項目を選択。『A–B間を測定』でカーソル間を集計します。\n"
            "『プロトコル解析』は取得済み波形を使用。EnDatは実験的な内蔵解析、その他はsigrok-cliが必要です。\n"
            "Mathの式には一覧のCH名を使用。異なる時間軸同士の演算はできません。\n"
            "セッションには全波形・色・表示範囲・A/B位置を保存。別PCでも開けます。\n"
            "Ctrl+EでCSV、Ctrl+Shift+EでPC解析用WVF/HDRを出力。本体設定は含みません。\n"
            "実機の取得はSTOP後に実行。RUN/STOPは実機の測定を操作します。\n"
            "『実機に接続して波形表示』で接続後、RUN/STOPボタンまたはSpaceで実機の測定を切り替えます。\n"
            "『操作中は本体LCDを消灯』は接続中のバックライトを消し、切断時に元の状態へ戻します。\n"
            "読み出し中の操作は通信の区切りで優先反映します。文字入力中のSpaceは通常の入力です。\n"
            "STOP後は最終波形を1回取得して保持し、カーソル測定・Mathを操作できます。\n"
            "プレビュー優先は転送時にSTOPし、元がRUNなら再開します。平均化は再開時にリセットされます。\n"
            "切断ボタンは最後の記録を全点取得してから通信を終了します。\n"
            "LOCALで本体操作に戻せます。接続だけでは取得・停止しません。\n"
            "『本体画面』はHTTPの画像表示専用モードです。RUN/STOPを変更せず、取得には数秒かかります。\n"
            "モードを切り替えても波形・Math・ズームは保持します。本体画像にMathやカーソル測定は適用しません。")


def main():
    parser = argparse.ArgumentParser(description="DL1640 Waveform Workbench")
    parser.add_argument("file", nargs="?", help="WVF/HDR, CSV, .scope.npz or .scope.json")
    args = parser.parse_args()
    application = W.QApplication(sys.argv[:1])
    configure_application(application)
    window = MainWindow()
    window.show()
    if args.file:
        window.open_path(args.file)
    sys.exit(application.exec())
