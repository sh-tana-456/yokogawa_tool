import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
import numpy as np
import pytest
from PySide6 import QtWidgets as W, QtTest
from yokogawa_tool.gui.app import MainWindow, configure_application
from yokogawa_tool.core.waveform import Trace


@pytest.fixture
def window():
    app = W.QApplication.instance() or W.QApplication([])
    configure_application(app)
    widget = MainWindow()
    widget.errors = []
    widget.error = widget.errors.append
    widget.show()
    app.processEvents()
    yield widget
    widget.set_live(False)
    widget.instrument_panel.invalidate()
    widget.dirty = False
    widget.close()


def frame(generation, offset=0):
    x = np.linspace(-1e-5, 1e-5, 201)
    return dict(generation=generation, waiting=False, running=False,
                traces=[Trace("CH1", x, 2+.1*np.sin(x*1e6)+offset)])


def enable(window):
    window.set_live(True)
    window._live_timer.stop()
    return window._live_generation


def test_user_disconnect_reads_full_frame_and_preserves_identical_math(window, monkeypatch):
    import yokogawa_tool.gui.app as module
    calls, closed = [], []
    class Backend:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): closed.append(True)
        def capture_live(self, allow_pause=True, capture_stopped=True):
            calls.append((allow_pause, capture_stopped))
            return frame(0)
    monkeypatch.setattr(module, 'DL1640', Backend)
    generation = enable(window)
    window.network_result('LIVE', 'test', frame(generation))
    window.expression.setText('CH1 * 2')
    window.add_expression()
    math_values = window.traces[-1].y.copy()
    window.request_live(False)
    for _ in range(200):
        QtTest.QTest.qWait(10)
        if not window.live_enabled and window.worker is None: break
    assert not window.errors and not window.live_enabled and window.worker is None
    assert calls == [(True, True)] and len(closed) == 1
    np.testing.assert_array_equal(window.traces[-1].y, math_values)
    assert len(window.traces) == 2


def test_disconnect_while_reading_queues_one_final_full_capture(window, monkeypatch):
    import threading
    import yokogawa_tool.gui.app as module
    entered, release = threading.Event(), threading.Event()
    calls = []
    class Backend:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def capture_live(self, allow_pause=True, capture_stopped=True):
            calls.append(capture_stopped)
            if len(calls) == 1:
                entered.set()
                assert release.wait(2)
            result = frame(0)
            if len(calls) == 2:
                result['traces'] = [Trace('CH1', np.linspace(-1e-5, 1e-5, 4008), np.zeros(4008))]
            return result
    monkeypatch.setattr(module, 'DL1640', Backend)
    enable(window)
    window.poll_live()
    assert entered.wait(1)
    window.request_live(False)
    assert window._disconnect_requested
    release.set()
    for _ in range(200):
        QtTest.QTest.qWait(10)
        if not window.live_enabled and window.worker is None: break
    assert not window.errors and not window.live_enabled
    assert calls == [True, True] and len(window.traces[0].x) == 4008


def test_supplied_session_renders_after_saved_view_recovery(window):
    path = Path(__file__).resolve().parents[1] / "samples/waveform.scope.npz"
    if not path.exists():
        pytest.skip("User-supplied regression fixture is not installed")
    # Reproduce opening the file after an unrelated, much wider time scale.
    window.plot.setRange(xRange=(-1, 1), yRange=(-10, 10), padding=0)
    window.open_path(path)
    W.QApplication.processEvents()
    assert window.view_recovered
    assert len(window.traces[0].x) == 4008
    assert len(window.curves[0].getData()[0]) > 2
    assert np.ptp(window.plot.viewRange()[0]) < np.ptp(window.traces[0].x)*2
    assert "補正" in window.statusBar().currentMessage()


def test_fit_uses_original_data_even_when_display_dataset_is_empty(window):
    x = np.linspace(-1e-5, 1e-5, 4008)
    window.plot.setRange(xRange=(-1, 1), yRange=(-10, 10), padding=0)
    window.set_traces([Trace("CH1", x, 2+.1*np.sin(x*1e6))], "regression",
                      dict(x_range=[-.0587, .0275], y_range=[1.67, 2.2]))
    W.QApplication.processEvents()
    assert window.view_recovered
    assert len(window.curves[0].getData()[0]) > 2
    assert np.ptp(window.plot.viewRange()[0]) < np.ptp(x)*2


def test_live_reuses_curves_and_preserves_zoom_and_colors(window):
    generation = enable(window)
    window.network_result("LIVE", "test", frame(generation))
    window.traces[0].color = "#334455"
    window.redraw()
    curve = window.curves[0]
    window.plot.setRange(xRange=(-2e-6, 3e-6), yRange=(1.8, 2.2), padding=0)
    before = np.array(window.plot.viewRange())
    window.network_result("LIVE", "test", frame(generation, .02))
    assert window.curves[0] is curve
    assert window.traces[0].color == "#334455"
    np.testing.assert_allclose(window.plot.viewRange(), before)
    assert window._live_count == 2 and window.math_group.isEnabled()
    window.set_live(False)
    assert window.math_group.isEnabled() and window.dirty


def test_late_live_result_cannot_overwrite_opened_file(window):
    generation = enable(window)
    window.network_result("LIVE", "test", frame(generation))
    window.dirty = False  # Simulate choosing to discard the last snapshot.
    window.open_path(Path(__file__).resolve().parents[1] / "demo/0000.WVF")
    original = window.traces[0].y.copy()
    assert not window.live_enabled
    window.network_result("LIVE", "test", frame(generation, 100))
    np.testing.assert_array_equal(window.traces[0].y, original)
    assert len(window.traces) == 3


def test_live_worker_does_not_overlap_or_build_request_backlog(window, monkeypatch):
    import yokogawa_tool.gui.app as module
    calls = []
    connections = []
    closed = []

    class Backend:
        def __init__(self, **kwargs): pass
        def __enter__(self):
            connections.append(self)
            return self
        def __exit__(self, *args): closed.append(self)
        def capture_live(self, allow_pause=True, capture_stopped=True):
            calls.append(1)
            return frame(0)

    monkeypatch.setattr(module, "DL1640", Backend)
    enable(window)
    window.poll_live()
    for _ in range(5): window.poll_live()
    for _ in range(100):
        QtTest.QTest.qWait(10)
        if window.worker is None: break
    assert len(calls) == 1 and window._live_count == 1
    window._live_timer.stop()
    window.poll_live()
    for _ in range(100):
        QtTest.QTest.qWait(10)
        if window.worker is None: break
    assert len(calls) == 2 and window._live_count == 2
    assert len(connections) == 1 and not closed
    window.set_live(False)
    assert closed == connections


def test_live_error_stops_automatic_requests(window, monkeypatch):
    errors = []
    monkeypatch.setattr(window, "error", errors.append)
    enable(window)
    window.network_failed("socket closed")
    assert not window.live_enabled and not window.instrument_panel.live_button.isChecked()
    assert not window._live_timer.isActive()
    assert errors == ["socket closed"]


def test_single_wait_keeps_previous_waveform(window):
    generation = enable(window)
    before = window.traces
    window.network_result("LIVE", "test", dict(generation=generation, waiting=True, running=True, traces=[]))
    assert window.traces is before and window._live_count == 0
    assert "完了待ち" in window.network_label.text()


def test_live_button_and_preview_only_mode(window):
    panel = window.instrument_panel
    assert panel.run_button.minimumHeight() >= 48
    assert panel.live_mode.count() == 1 and panel.live_mode.currentData() is True
    generation = enable(window)
    assert panel.live_button.isChecked() and "解除" in panel.live_button.text()
    assert panel.live_button.property("role") == "read"
    requests = []
    window.network = lambda action, values: requests.append((action, values))
    window.poll_live()
    assert requests == [("LIVE", dict(generation=generation, allow_pause=True, capture_stopped=True))]
    window.set_live(False)
    assert not panel.live_button.isChecked() and "接続" in panel.live_button.text()


def test_live_interval_includes_transfer_time(window, monkeypatch):
    import yokogawa_tool.gui.app as module
    enable(window)
    window.instrument_panel.live_interval.setValue(100)
    window._network_started = 10.
    monkeypatch.setattr(module.time, "monotonic", lambda: 10.075)
    window.network_finished()
    assert window._live_timer.interval() == 25
    monkeypatch.setattr(module.time, "monotonic", lambda: 10.15)
    window.network_finished()
    assert window._live_timer.interval() == 0
