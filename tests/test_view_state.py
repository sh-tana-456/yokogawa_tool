import numpy as np
from pathlib import Path
from yokogawa_tool.core.waveform import Trace, load_session
from yokogawa_tool.gui.view_state import restore_view


def test_attached_session_has_valid_data_but_excessive_saved_zoom():
    path = Path(__file__).resolve().parents[1] / "samples/waveform.scope.npz"
    if not path.exists():
        import pytest
        pytest.skip("User-supplied regression fixture is not installed")
    traces, saved = load_session(path)
    original_x = traces[0].x.copy()
    original_y = traces[0].y.copy()
    assert len(original_x) == 4008
    assert saved["x_range"][1]-saved["x_range"][0] > np.ptp(original_x)*1000
    restored, reset = restore_view(traces, saved)
    assert reset and "x_range" not in restored and "y_range" not in restored
    assert "cursor_a" not in restored and "cursor_b" not in restored
    np.testing.assert_array_equal(traces[0].x, original_x)
    np.testing.assert_array_equal(traces[0].y, original_y)


def test_useful_zoom_and_theme_are_kept_and_input_is_not_mutated():
    traces = [Trace("CH1", [0, 1, 2], [3, 4, 5])]
    saved = dict(x_range=[.5, 1.5], y_range=[3.5, 4.5], cursor_a=1, cursor_b=1.2, theme="xp")
    restored, reset = restore_view(traces, saved)
    assert restored == saved and not reset
    restored.pop("theme")
    assert saved["theme"] == "xp"


def test_invalid_and_outside_ranges_are_recovered():
    traces = [Trace("CH1", [0, 1, 2], [3, 4, 5])]
    for pair in ([8, 9], [2, 1], [0, float("inf")], [0], None):
        restored, reset = restore_view(traces, dict(x_range=pair))
        assert reset and "x_range" not in restored
    restored, reset = restore_view(traces, dict(y_range=[10, 20]))
    assert reset and "y_range" not in restored


def test_extreme_zoom_out_recovery_without_external_fixture():
    traces = [Trace("CH1", np.linspace(-1e-5, 1e-5, 4008), np.linspace(1.5, 2.5, 4008))]
    restored, reset = restore_view(traces, dict(x_range=[-.0587, .0275], y_range=[1.67, 2.2], cursor_a=-.027))
    assert reset and not restored
