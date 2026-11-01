"""Compare dense square-wave repaint cost without connecting to an instrument."""
from pathlib import Path
import json
import sys
import time
import numpy as np
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from yokogawa_tool.gui.app import MainWindow, configure_application
from yokogawa_tool.core.waveform import Trace
import yokogawa_tool.gui.rendering as rendering

app = QApplication([])
configure_application(app)
window = MainWindow()
window.resize(2048, 1126)
original_aa = window.antialias_checkbox.isChecked()
classify = rendering.dense_transitions
results = {}


def previous_classifier(x, y, x_range, y_range, width, *args, **kwargs):
    """The point-density rule used before the intermediate-zoom fix."""
    if x is None or y is None or width <= 0 or len(x) < width:
        return False
    lo = max(0, np.searchsorted(x, x_range[0]) - 1)
    hi = min(len(x), np.searchsorted(x, x_range[1]) + 1)
    if hi - lo < width:
        return False
    travel = np.abs(np.diff(np.clip(y[lo:hi], *y_range))) / (y_range[1] - y_range[0])
    return np.sum(travel[np.isfinite(travel)]) > width * .35


try:
    window.antialias_checkbox.setChecked(True)
    x = np.linspace(-.025, .025, 10020)
    rng = np.random.default_rng(0)
    y = (np.arange(len(x)) % 4 < 2) * 3.3 + rng.normal(0, .02, len(x))
    window.set_traces([Trace("CH1", x, y), Trace("CH2", x, y * .8 + .1)], "Dense benchmark")
    window.show()
    app.processEvents()
    for scenario, limits in (("full_view", (-.025, .025)),
                             ("intermediate_zoom", (-.00195, -.0005))):
        window.plot.setXRange(*limits, padding=0)
        results[scenario] = {}
        for name, classifier in (("previous", previous_classifier), ("adaptive", classify)):
            # Replace the classifier, not a Qt virtual paint method: those
            # wrappers cannot reliably be replaced after instantiation.
            rendering.dense_transitions = classifier
            samples = []
            for i in range(4):
                started = time.perf_counter()
                for curve, trace in zip(window.curves, window.traces):
                    curve.setData(trace.x, trace.y + i * .0001)
                for curve, trace in zip(window.overview.listDataItems(), window.traces):
                    curve.setData(trace.x, trace.y + i * .0001)
                app.processEvents()
                window.grab()  # Include actual raster painting, not just setData.
                samples.append(time.perf_counter() - started)
            results[scenario][name] = {"median_seconds": float(np.median(samples)), "samples_seconds": samples}
    print(json.dumps(results, indent=2))
finally:
    rendering.dense_transitions = classify
    window.antialias_checkbox.setChecked(original_aa)
    window.dirty = False
    window.close()
