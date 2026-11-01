"""A separate image monitor; waveform analysis data is never modified here."""
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets as W
from yokogawa_tool.gui.instrument_panel import StatusLabel


class ScreenView(W.QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(W.QGraphicsScene(self))
        self.image = W.QGraphicsPixmapItem()
        self.scene().addItem(self.image)
        self.setBackgroundBrush(QtGui.QColor("#101720"))
        self.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        self.setDragMode(W.QGraphicsView.ScrollHandDrag)
        self.fitting = True

    def show_image(self, image):
        self.image.setPixmap(QtGui.QPixmap.fromImage(image))
        self.scene().setSceneRect(self.image.boundingRect())
        if self.fitting:
            self.fit_image()

    def fit_image(self):
        self.fitting = True
        if not self.image.pixmap().isNull():
            self.fitInView(self.image, QtCore.Qt.KeepAspectRatio)

    def original_size(self):
        self.fitting = False
        self.resetTransform()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fitting:
            self.fit_image()

    def wheelEvent(self, event):
        if self.image.pixmap().isNull() or not event.angleDelta().y():
            event.ignore()
            return
        self.fitting = False
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        if .1 <= self.transform().m11() * factor <= 12:
            self.scale(factor, factor)
        event.accept()


class ScreenPanel(W.QWidget):
    requested = QtCore.Signal()
    auto_requested = QtCore.Signal(bool)
    connection_changed = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.png = None
        self.frames = 0
        layout = W.QVBoxLayout(self)
        description = W.QLabel("本体画面モード：DL1640の画面画像を表示します。取得時にRUN/STOPは操作しません。\n"
                               "波形データの解析は「波形・解析」モードで行います。画像の更新には数秒かかります。")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.target = W.QLabel()
        self.target.setTextFormat(QtCore.Qt.PlainText)
        self.target.setWordWrap(True)
        layout.addWidget(self.target)
        row = W.QHBoxLayout()
        self.refresh = W.QPushButton("本体画面を取得")
        self.refresh.setProperty("role", "capture")
        self.refresh.clicked.connect(self.requested)
        row.addWidget(self.refresh)
        self.auto_button = W.QPushButton("▶ 本体画面の自動更新を開始")
        self.auto_button.setMinimumHeight(48)
        self.auto_button.setCheckable(True)
        self.auto_button.setProperty("role", "capture")
        self.auto_button.toggled.connect(self.auto_requested)
        row.addWidget(self.auto_button)
        row.addWidget(W.QLabel("更新周期"))
        self.interval = W.QSpinBox()
        self.interval.setRange(1, 60)
        self.interval.setValue(10)
        self.interval.setSuffix(" s")
        row.addWidget(self.interval)
        row.addWidget(W.QLabel("HTTPポート"))
        self.port = W.QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(80)
        self.port.valueChanged.connect(self.connection_changed)
        row.addWidget(self.port)
        row.addStretch()
        layout.addLayout(row)
        self.status = StatusLabel("未取得 · 左の「実機操作」でIP・認証を設定し、「本体画面を取得」を押してください。")
        layout.addWidget(self.status)
        self.view = ScreenView()
        layout.addWidget(self.view, 1)
        row = W.QHBoxLayout()
        for text, callback in (("ウィンドウに合わせる", self.view.fit_image), ("原寸", self.view.original_size)):
            button = W.QPushButton(text)
            button.clicked.connect(callback)
            row.addWidget(button)
        self.save = W.QPushButton("本体画面をPNG保存")
        self.save.setEnabled(False)
        self.save.clicked.connect(self.save_dialog)
        row.addWidget(self.save)
        row.addStretch()
        row.addWidget(W.QLabel("ホイール：画像拡大縮小 / ドラッグ：移動"))
        layout.addLayout(row)

    def set_auto_state(self, enabled):
        self.auto_button.blockSignals(True)
        self.auto_button.setChecked(enabled)
        self.auto_button.blockSignals(False)
        self.auto_button.setText("■ 本体画面の自動更新を終了" if enabled else "▶ 本体画面の自動更新を開始")
        self.auto_button.setProperty("role", "stop" if enabled else "capture")
        self.auto_button.style().unpolish(self.auto_button)
        self.auto_button.style().polish(self.auto_button)

    def set_busy(self, busy):
        self.refresh.setEnabled(not busy)
        self.port.setEnabled(not busy)

    def clear_image(self):
        self.png = None
        self.frames = 0
        self.view.image.setPixmap(QtGui.QPixmap())
        self.save.setEnabled(False)
        self.status.setText("接続先が変わりました。本体画面を取得してください。")

    def set_frame(self, data, host, seconds):
        image = QtGui.QImage.fromData(data, "PNG")
        if image.isNull():
            raise ValueError("本体画面のPNGをデコードできませんでした。")
        self.png = data
        self.frames += 1
        self.view.show_image(image)
        self.save.setEnabled(True)
        self.status.setText(f"{host} · {image.width()}×{image.height()} · 取得 {seconds:.2f}秒 · {self.frames}枚\n"
                            "本体の測定状態は変更していません。")

    def save_dialog(self):
        if self.png is None:
            return
        path, _ = W.QFileDialog.getSaveFileName(self, "本体画面を保存", "dl1640-screen.png", "PNG (*.png)")
        if path:
            try:
                Path(path).write_bytes(self.png)
            except OSError as exc:
                self.status.setText(f"画像を保存できませんでした: {exc}")
