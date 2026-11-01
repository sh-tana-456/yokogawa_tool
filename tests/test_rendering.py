import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import numpy as np
from PySide6.QtWidgets import QApplication
from yokogawa_tool.gui.rendering import dense_transitions
from yokogawa_tool.core.waveform import Trace, save_session, load_session
from yokogawa_tool.gui.app import MainWindow, configure_application


def test_density_uses_visible_transitions_not_just_sample_count():
    x = np.linspace(0, 1, 10000)
    square = (np.arange(len(x)) % 4 < 2) * 3.3
    assert dense_transitions(x, square, [0, 1], [-.2, 3.5], 1000)
    assert not dense_transitions(x, square, [.49, .491], [-.2, 3.5], 1000)
    assert not dense_transitions(x, np.sin(x), [0, 1], [-1, 1], 1000)
    assert not dense_transitions(x, square, [0, 1], [10, 20], 1000)
    gaps = np.zeros(len(x)); gaps[1::2] = np.nan; gaps[2::4] = 3.3
    assert not dense_transitions(x, gaps, [0, 1], [-.2, 3.5], 1000)


def test_sparse_tall_edges_are_expensive_even_below_one_sample_per_pixel():
    x = np.linspace(0, 1, 300)
    square = (np.arange(len(x)) % 4 < 2) * 3.3
    assert dense_transitions(x, square, [0, 1], [-.2, 3.5], 2000, 700)
    assert not dense_transitions(x, np.linspace(0, 3.3, len(x)), [0, 1], [-.2, 3.5], 2000, 700)
    assert not dense_transitions([0, .5, 1], [0, 0, 3.3], [0, 1], [-.2, 3.5], 2000, 700)


def test_stroke_budget_hysteresis_and_viewport_height():
    x = np.linspace(0, 1, 18)
    y = np.arange(len(x)) % 2
    assert not dense_transitions(x, y, [0, 1], [0, 1], 1000, 600)
    assert dense_transitions(x, y, [0, 1], [0, 1], 1000, 600, budget=7800)
    assert not dense_transitions(x, y, [0, 1], [0, 1], 1000, 100, budget=7800)


def test_dense_raster_zoom_recovery_and_original_data_preservation(tmp_path):
    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    original_aa = window.antialias_checkbox.isChecked()
    window.antialias_checkbox.setChecked(True)
    x = np.linspace(0, 1, 100000)
    y = (np.arange(len(x)) % 4 < 2) * 3.3
    y[50000] = 4.2  # Preserve a narrow peak, even in the overview.
    trace = Trace('CH1', x.copy(), y.copy())
    try:
        window.set_traces([trace], 'Dense test')
        window.show(); app.processEvents(); window.grab()
        main, overview = window.curves[0], window.overview.listDataItems()[0]
        assert main.curve.dense and overview.curve.dense
        displayed_x, displayed_y = main.getData()
        assert len(displayed_x) < len(x) / 5
        assert np.nanmax(displayed_y) == 4.2 and np.nanmin(displayed_y) == 0
        assert main.curve.opts['antialias'] is True  # User setting survives painting.
        assert main.curve.opts['pen'].widthF() == 1.5
        window.plot.setXRange(.1, .103, padding=0)
        app.processEvents(); window.grab()
        assert len(main.getData()[0]) < window.plot.getViewBox().width()
        assert main.curve.dense  # Screenshot case: sparse but long vertical edges.
        window.plot.setXRange(.1, .1001, padding=0)
        app.processEvents(); window.grab()
        assert not main.curve.dense and overview.curve.dense
        np.testing.assert_array_equal(trace.x, x)
        np.testing.assert_array_equal(trace.y, y)
        np.testing.assert_array_equal(main.yData, y)
        path = tmp_path / 'dense.scope.npz'
        save_session(path, window.traces)
        restored, _ = load_session(path)
        np.testing.assert_array_equal(restored[0].y, y)
    finally:
        window.antialias_checkbox.setChecked(original_aa)
        window.dirty = False
        window.close()
