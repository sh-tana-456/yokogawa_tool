"""Compare raster paths with identical AA-enabled data, axes and zoom gestures."""
from pathlib import Path
import sys
import time
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from yokogawa_tool.gui.app import MainWindow, configure_application

app = QApplication([])
configure_application(app)
window = MainWindow()
window.show()
window.open_path(ROOT / "demo/0000.WVF")
original = window.antialias_checkbox.isChecked()
window.antialias_checkbox.setChecked(True)
app.processEvents()
for mode in ("auto", "on"):
    for item in window.curves:
        item.curve.setSegmentedLineMode(mode)
    window.plot.setRange(xRange=(-.001, .001), yRange=(-.5, 4), padding=0)
    app.processEvents()
    started = time.perf_counter()
    for i in range(12):
        span = .002 * .88**i
        window.plot.setXRange(-span/2, span/2, padding=0)
        app.processEvents()
    print(f"{mode}: 12 zoom frames in {time.perf_counter()-started:.3f}s (AA ON)")
window.antialias_checkbox.setChecked(original)
window.dirty = False
window.close()
