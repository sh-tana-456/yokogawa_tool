import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from yokogawa_tool.core.interpolation import interpolate_display
from yokogawa_tool.gui.app import MainWindow, configure_application
from yokogawa_tool.core.waveform import Trace, save_session, load_session


def test_cubic_retains_knots_and_preserves_monotone_interval_bounds():
    x = np.array([0., .1, .4, 1, 2])
    y = np.array([0., 1, 1, -2, 3])
    xx, yy = interpolate_display(x, y, 1000)
    assert len(xx) > len(x) and len(xx) <= 2 * 1000 + len(x)
    np.testing.assert_array_equal(yy[np.searchsorted(xx, x)], y)
    for i in range(len(x)-1):
        values = yy[(xx >= x[i]) & (xx <= x[i+1])]
        assert np.min(values) >= min(y[i:i+2]) - 1e-12
        assert np.max(values) <= max(y[i:i+2]) + 1e-12


def test_linear_data_and_nan_gap_are_preserved():
    x = np.arange(7.)
    y = 2*x + 1
    xx, yy = interpolate_display(x, y, 500)
    np.testing.assert_allclose(yy, 2*xx+1)
    y[3] = np.nan
    xx, yy = interpolate_display(x, y, 500)
    assert np.all(np.isnan(yy[(xx > 2) & (xx < 4)]))
    assert yy[np.searchsorted(xx, 2)] == 5
    assert yy[np.searchsorted(xx, 4)] == 9


def test_peak_envelope_and_dense_data_are_not_interpolated():
    for x, y, width in ((np.array([0., 0, 1, 1]), np.array([0., 1, 0, 1]), 1000),
                        (np.arange(10000.), np.zeros(10000), 1000)):
        xx, yy = interpolate_display(x, y, width)
        assert xx is x and yy is y


def test_gui_interpolation_metadata_and_session_keep_original_samples(tmp_path):
    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    original = window.interpolation_combo.currentData()
    trace = Trace('CH1', np.arange(5.)*.001, np.array([0., 1, 1, 0, 2]),
                  metadata={'sample_rate': 1000, 'time_div': .001, 'vertical_div': .5})
    try:
        window.set_traces([trace], 'Interpolation')
        window.show(); app.processEvents()
        window.interpolation_combo.setCurrentIndex(window.interpolation_combo.findData('cubic'))
        app.processEvents()
        item = window.curves[0]
        assert len(item.curve.xData) > len(trace.x)
        np.testing.assert_array_equal(item.xData, trace.x)
        np.testing.assert_array_equal(item.yData, trace.y)
        info = window.channel_info_labels['CH1'].text()
        assert 'dt' in info and 'Sa/s' in info and 'T/div' in info and 'V/div' in info
        window.interpolation_combo.setCurrentIndex(window.interpolation_combo.findData('step'))
        assert item.curve.opts['stepMode'] == 'left'
        window.interpolation_combo.setCurrentIndex(window.interpolation_combo.findData('cubic'))
        path = tmp_path / 'curve.scope.npz'
        save_session(path, window.traces, window.view_state())
        restored, view = load_session(path)
        np.testing.assert_array_equal(restored[0].y, trace.y)
        assert view['interpolation'] == 'cubic'
        assert restored[0].metadata['vertical_div'] == .5
        irregular = Trace('CH2', [0, 1, 3], [0, 1, 2])
        assert 'non-uniform' in window.channel_info_text(irregular)
        assert 'N/A' in window.channel_info_text(irregular)
    finally:
        window.interpolation_combo.setCurrentIndex(window.interpolation_combo.findData(original))
        window.dirty = False
        window.close()
