"""Compact front-panel style numeric adjustment with engineering steps."""
import math
from PySide6 import QtCore, QtWidgets as W
from yokogawa_tool.acquisition.settings import scalar


class QuantityControl(W.QWidget):
    edited = QtCore.Signal()

    def __init__(self, low, high, *, unit="", step=.1, engineering=False, parent=None):
        super().__init__(parent)
        self.low, self.high = low, high
        self.unit, self.step = unit, step
        self.engineering = engineering
        self.fine = False
        layout = W.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.minus = W.QPushButton("−")
        self.minus.setProperty("role", "decrease")
        self.editor = W.QLineEdit()
        self.editor.setAlignment(QtCore.Qt.AlignCenter)
        self.plus = W.QPushButton("＋")
        self.plus.setProperty("role", "increase")
        for button, direction in ((self.minus, -1), (self.plus, 1)):
            button.setFixedWidth(30)
            button.setAutoRepeat(True)
            button.setAutoRepeatDelay(350)
            button.setAutoRepeatInterval(90)
            button.setToolTip("押し続けると連続して調整できます")
            button.clicked.connect(lambda checked=False, d=direction: self.adjust(d))
        layout.addWidget(self.minus)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.plus)
        self.editor.editingFinished.connect(self.commit)
        self._committed = ""

    def text(self):
        return self.editor.text()

    def setText(self, text):
        text = str(text)
        try:
            if self.unit == "V|A":
                try:
                    value = scalar(text, "V")
                except ValueError:
                    value = scalar(text, "A")
            else:
                value = scalar(text, self.unit)
            exponent = max(-12, min(9, int(math.floor(math.log10(abs(value))/3)*3))) if value else 0
            if not self.unit and not self.engineering:
                exponent = 0
            prefix = {-12: "p", -9: "n", -6: "µ", -3: "m", 0: "", 3: "k", 6: "M", 9: "G"}[exponent]
            suffix = self.unit if self.unit != "V|A" else ""
            text = f"{value/10**exponent:.12g}{prefix}{suffix}"
        except ValueError:
            pass
        self.editor.setText(text)
        self.editor.setModified(False)
        self._committed = self.text()

    def setPlaceholderText(self, text):
        self.editor.setPlaceholderText(text)

    def value(self):
        if self.unit == "V|A":
            try:
                return scalar(self.text(), "V")
            except ValueError:
                return scalar(self.text(), "A")
        return scalar(self.text(), self.unit)

    def commit(self):
        if self.text() != self._committed:
            self._committed = self.text()
            self.editor.setModified(False)
            self.edited.emit()

    def adjust(self, direction):
        try:
            value = self.value()
        except ValueError:
            return
        if self.engineering:
            steps = sorted({self.low, self.high} | {m*10.**e for e in range(-12, 10)
                           for m in (1, 2, 5) if self.low <= m*10.**e <= self.high})
            candidates = [v for v in steps if v > value*(1+1e-10)] if direction > 0 else [v for v in steps if v < value*(1-1e-10)]
            result = (min(candidates) if direction > 0 else max(candidates)) if candidates else value
        else:
            step = self.step() if callable(self.step) else self.step
            result = value + direction*step*(.1 if self.fine else 1)
        result = min(self.high, max(self.low, result))
        if not math.isclose(value, result, rel_tol=1e-12, abs_tol=1e-18):
            self.setText(f"{result:.12g}")
            self.edited.emit()
