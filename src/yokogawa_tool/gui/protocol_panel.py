"""Snapshot protocol analysis dialog, independent of the instrument worker."""
import csv
from PySide6 import QtCore, QtWidgets as W
from yokogawa_tool.protocols import PROTOCOLS, decode
from yokogawa_tool.core.measurements import signal_levels


class DecodeWorker(QtCore.QThread):
    result = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
    def run(self):
        try:
            self.result.emit(self.operation())
        except Exception as exc:
            self.failed.emit(str(exc))


class ProtocolDialog(W.QDialog):
    def __init__(self, traces, settings, parent=None):
        super().__init__(parent)
        self.traces, self.settings, self.worker, self.events = list(traces), settings, None, []
        self.setWindowTitle('プロトコル解析 · 取得済み波形のスナップショット')
        self.resize(1000, 750)
        layout = W.QVBoxLayout(self)
        form = W.QFormLayout()
        layout.addLayout(form)
        self.protocol = W.QComboBox()
        for key in PROTOCOLS:
            self.protocol.addItem('EnDat 2.1 / 2.2 (experimental)' if key == 'endat' else key.upper(), key)
        form.addRow('プロトコル', self.protocol)
        tool_row = W.QHBoxLayout()
        self.tool = W.QLineEdit(str(settings.value('sigrok_cli', 'sigrok-cli')))
        tool_row.addWidget(self.tool)
        browse = W.QPushButton('参照')
        self.browse = browse
        browse.clicked.connect(self.browse_tool)
        tool_row.addWidget(browse)
        form.addRow('sigrok-cli', tool_row)
        self.channel_group = W.QGroupBox('信号としきい値（波形の単位）')
        self.channel_form = W.QFormLayout(self.channel_group)
        layout.addWidget(self.channel_group)
        self.auto = W.QCheckBox('Low/Highからしきい値を自動推定')
        self.auto.setChecked(True)
        self.auto.toggled.connect(self.update_thresholds)
        layout.addWidget(self.auto)
        self.options_group = W.QGroupBox('復号設定')
        self.options_form = W.QFormLayout(self.options_group)
        layout.addWidget(self.options_group)
        self.run = W.QPushButton('スナップショットを解析')
        self.run.clicked.connect(self.start_decode)
        layout.addWidget(self.run)
        self.status = W.QLabel('別途sigrok-cliとlibsigrokdecodeが必要です。欠損のない、同時刻・等間隔のCHを使用します。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = W.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['開始 [s]', '終了 [s]', '種類', '内容'])
        self.table.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self.zoom_event)
        layout.addWidget(self.table, 1)
        export = W.QPushButton('復号結果をCSVに保存')
        export.clicked.connect(self.export)
        layout.addWidget(export)
        self.protocol.currentIndexChanged.connect(self.rebuild)
        self.rebuild()

    def browse_tool(self):
        path, _ = W.QFileDialog.getOpenFileName(self, 'sigrok-cliを選択')
        if path:
            self.tool.setText(path)

    def rebuild(self, *args):
        for form in (self.channel_form, self.options_form):
            while form.rowCount():
                form.removeRow(0)
        self.channels, self.thresholds, self.options = {}, {}, {}
        protocol = self.protocol.currentData()
        self.tool.setEnabled(protocol != 'endat')
        self.browse.setEnabled(protocol != 'endat')
        self.status.setText('EnDat内蔵解析（実信号未検証）。位置ビット長はエンコーダーに合わせて指定してください。'
                            if protocol == 'endat' else 'sigrok-cliとlibsigrokdecodeが必要です。')
        for index, role in enumerate(PROTOCOLS[protocol]):
            row = W.QHBoxLayout()
            choice = W.QComboBox()
            choice.addItem('なし', None)
            for trace in self.traces:
                choice.addItem(f'{trace.name} [{trace.unit}]', trace.name)
            if index < 2 and index < len(self.traces):
                choice.setCurrentIndex(index + 1)
            elif index == 0 and self.traces:
                choice.setCurrentIndex(1)
            threshold = W.QDoubleSpinBox()
            threshold.setRange(-1e9, 1e9)
            threshold.setDecimals(9)
            threshold.setSingleStep(.1)
            self.channels[role], self.thresholds[role] = choice, threshold
            choice.currentIndexChanged.connect(self.update_thresholds)
            row.addWidget(choice, 2); row.addWidget(threshold, 1)
            self.channel_form.addRow(role.upper(), row)
        def spin(key, label, value, low, high):
            widget = W.QSpinBox(); widget.setRange(low, high); widget.setValue(value)
            self.options[key] = widget; self.options_form.addRow(label, widget)
        def combo(key, label, values):
            widget = W.QComboBox()
            for title, value in values:
                widget.addItem(title, value)
            self.options[key] = widget; self.options_form.addRow(label, widget)
        if protocol == 'uart':
            spin('baudrate', 'ボーレート [bit/s]', 115200, 1, 100000000)
            spin('data_bits', 'データビット', 8, 5, 9)
            combo('parity', 'パリティ', [('なし', 'none'), ('偶数', 'even'), ('奇数', 'odd')])
            combo('stop_bits', 'ストップビット', [('1', '1.0'), ('1.5', '1.5')])
            combo('invert_rx', '極性', [('通常', 'no'), ('反転', 'yes')])
        elif protocol == 'spi':
            combo('cpol', 'クロック極性 CPOL', [('0', 0), ('1', 1)])
            combo('cpha', 'クロック位相 CPHA', [('0', 0), ('1', 1)])
            spin('wordsize', 'ワード長 [bit]', 8, 1, 32)
            combo('bitorder', 'ビット順', [('MSB first', 'msb-first'), ('LSB first', 'lsb-first')])
            combo('cs_polarity', 'CS極性', [('Low有効', 'active-low'), ('High有効', 'active-high')])
        elif protocol == 'can':
            spin('nominal_bitrate', 'ビットレート [bit/s]', 500000, 1, 10000000)
            spin('sample_point', 'サンプルポイント [%]', 70, 10, 95)
        elif protocol == 'endat':
            spin('position_bits', 'Position bits (ST + MT)', 25, 1, 64)
            spin('initial_clocks', 'Clocks before mode command', 2, 0, 8)
            spin('turnaround_clocks', 'Turnaround clocks', 2, 0, 8)
            spin('additional', 'Additional blocks (2.2)', 0, 0, 2)
            for key, label, value, low, high in (
                    ('idle_gap_us', 'Idle gap [µs]', 10, .01, 1e6),
                    ('response_delay_ns', 'Response delay [ns]', 0, -1e6, 1e6)):
                widget = W.QDoubleSpinBox()
                widget.setDecimals(2); widget.setRange(low, high); widget.setValue(value)
                self.options[key] = widget; self.options_form.addRow(label, widget)
            combo('invert_clk', 'CLOCK polarity', [('Normal', 0), ('Inverted', 1)])
            combo('invert_data', 'DATA polarity', [('Normal', 0), ('Inverted', 1)])
        self.update_thresholds()

    def update_thresholds(self, *args):
        if not hasattr(self, 'channels'):
            return
        import numpy as np
        for role, choice in self.channels.items():
            widget = self.thresholds[role]
            widget.setEnabled(not self.auto.isChecked())
            if self.auto.isChecked():
                trace = next((t for t in self.traces if t.name == choice.currentData()), None)
                if trace is not None:
                    low, high = signal_levels(trace.y[np.isfinite(trace.y)])
                    if np.isfinite(low + high):
                        widget.setValue((low + high)/2)

    def start_decode(self):
        if self.worker is not None:
            return
        protocol = self.protocol.currentData()
        channels = {role: next(t for t in self.traces if t.name == widget.currentData())
                    for role, widget in self.channels.items() if widget.currentData() is not None}
        thresholds = {role: widget.value() for role, widget in self.thresholds.items()}
        options = {key: widget.currentData() if isinstance(widget, W.QComboBox) else widget.value()
                   for key, widget in self.options.items()}
        tool = self.tool.text().strip()
        self.settings.setValue('sigrok_cli', tool)
        self.worker = DecodeWorker(lambda: decode(protocol, channels, thresholds, options, tool), self)
        self.run.setEnabled(False)
        for widget in (self.protocol, self.channel_group, self.options_group, self.auto, self.tool, self.browse):
            widget.setEnabled(False)
        self.status.setText('解析中…（元データと測定状態は変更しません）')
        self.worker.result.connect(self.show_events)
        self.worker.failed.connect(self.status.setText)
        self.worker.finished.connect(self.finished_decode)
        self.worker.start()

    def finished_decode(self):
        self.run.setEnabled(True)
        for widget in (self.protocol, self.channel_group, self.options_group, self.auto, self.tool, self.browse):
            widget.setEnabled(True)
        self.tool.setEnabled(self.protocol.currentData() != 'endat')
        self.browse.setEnabled(self.protocol.currentData() != 'endat')
        self.update_thresholds()
        self.worker.deleteLater()
        self.worker = None

    def show_events(self, events):
        self.events = events
        self.table.setRowCount(min(len(events), 10000))
        for row, event in enumerate(events[:10000]):
            for column, value in enumerate((f'{event.start:.12g}', f'{event.end:.12g}', event.kind, event.text)):
                self.table.setItem(row, column, W.QTableWidgetItem(value))
        self.status.setText(f'{len(events):,}件。先頭10,000件まで表示、CSVは全件出力。ダブルクリックで波形へ移動。')

    def zoom_event(self, row, column):
        if row < len(self.events) and self.parent() is not None:
            event = self.events[row]
            self.parent().cursor_a.setValue(event.start)
            self.parent().cursor_b.setValue(event.end)
            self.parent().zoom_cursors()

    def export(self):
        path, _ = W.QFileDialog.getSaveFileName(self, '復号結果を保存', 'protocol.csv', 'CSV (*.csv)')
        if path:
            try:
                with open(path, 'w', encoding='utf-8', newline='') as stream:
                    writer = csv.writer(stream)
                    writer.writerow(['start_s', 'end_s', 'kind', 'text'])
                    writer.writerows((e.start, e.end, e.kind, e.text) for e in self.events)
            except OSError as exc:
                self.status.setText(str(exc))

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.status.setText('解析が終了してから閉じてください（最大30秒）。')
            event.ignore()
        else:
            event.accept()
