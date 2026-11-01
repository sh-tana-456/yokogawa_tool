import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import threading
import numpy as np
import pytest
from PySide6 import QtCore, QtGui, QtWidgets as W, QtTest
from yokogawa_tool.gui.app import MainWindow, configure_application
from yokogawa_tool.core.waveform import Trace
from test_panel_sync import DATA


@pytest.fixture
def window():
    app = W.QApplication.instance() or W.QApplication([])
    configure_application(app)
    window = MainWindow()
    window.errors = []
    window.error = window.errors.append
    window.show()
    window.activateWindow()
    window.setFocus()
    app.processEvents()
    yield window
    window.set_live(False)
    window.instrument_panel.invalidate()
    window.dirty = False
    window.close()


def wait_idle(window):
    for _ in range(200):
        QtTest.QTest.qWait(10)
        if window.worker is None and not window._pending_run_toggle:
            break
    assert window.worker is None and not window.errors
    window._live_timer.stop()


def test_old_device_errors_are_nonmodal_and_do_not_invalidate_run(window):
    window.network_result("RUN_TOGGLE", "test", dict(DATA, running=True,
                          warnings=['609,"Execution error;"']))
    assert not window.errors
    assert window.instrument_panel.running is True
    assert window.instrument_panel.run_button.isEnabled()
    assert "609" in window.statusBar().currentMessage()
    assert "操作前" in window.network_label.toolTip()


def test_space_queues_stop_during_transfer_and_never_restarts_after_stop(window, monkeypatch):
    import yokogawa_tool.gui.app as module
    entered, release = threading.Event(), threading.Event()
    actual = dict(DATA, running=True)
    calls = []
    def traces():
        return [Trace("CH1", np.linspace(0, 1, 10), np.arange(10.))]
    class Backend:
        def __init__(self, **config): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def capture_live(self, allow_pause=True, capture_stopped=True):
            if actual["running"]:
                calls.append("pause")
                actual["running"] = False
                entered.set()
                assert release.wait(2)
                actual["running"] = True
                calls.append("resume")
                return dict(running=True, waiting=False, traces=traces())
            if not capture_stopped:
                return dict(running=False, waiting=True, reason="stopped", traces=[])
            calls.append("stopped_frame")
            return dict(running=False, waiting=False, traces=traces())
        def set_running(self, running, channel):
            actual["running"] = running
            calls.append("RUN" if actual["running"] else "STOP")
            return dict(actual)
    monkeypatch.setattr(module, "DL1640", Backend)
    window.instrument_panel.update_settings(actual)
    window.set_live(True)
    window._live_timer.stop()
    window.poll_live()
    try:
        assert entered.wait(1)
        assert window.instrument_panel.run_button.isEnabled()
        assert window.instrument_panel.run_button.property("role") == "stop"
        QtTest.QTest.keyClick(window, QtCore.Qt.Key_Space)
        assert window._pending_run_toggle
        assert window.instrument_panel.run_button.isEnabled()
        assert "STOP" not in calls
    finally:
        release.set()
    wait_idle(window)
    assert calls[:3] == ["pause", "resume", "STOP"]
    assert not actual["running"] and window.live_enabled
    assert window.instrument_panel.run_button.isEnabled()
    window.poll_live()
    wait_idle(window)
    assert window._stopped_frame_valid and window.math_group.isEnabled()
    frame = window.traces
    window.poll_live()
    wait_idle(window)
    assert window.traces is frame and calls.count("stopped_frame") == 1
    assert calls.count("RUN") == 0


def test_busy_button_emits_without_disabled_blink(window):
    panel = window.instrument_panel
    panel.update_settings(dict(DATA, running=True))
    requests = []
    panel.requested.disconnect(window.network)
    panel.requested.connect(lambda action, values: requests.append(action))
    for _ in range(3):
        panel.set_busy(True)
        assert panel.run_button.isEnabled() and panel.run_button.property("role") == "stop"
        panel.run_button.click()
        panel.set_busy(False)
    assert requests == ["TOGGLE_RUN"]*3


def test_stopped_state_poll_preserves_math_and_zoom(window):
    window.set_live(True)
    window._live_timer.stop()
    generation = window._live_generation
    trace = Trace("CH1", np.linspace(0, 1, 10), np.arange(10.))
    window.network_result("LIVE", "test", dict(generation=generation, running=False, waiting=False, traces=[trace]))
    window.expression.setText("CH1 * 2")
    window.add_expression()
    window.plot.setXRange(.2, .7, padding=0)
    traces = window.traces
    ranges = np.array(window.plot.viewRange())
    requests = []
    window.network = lambda action, values: requests.append((action, values))
    window.poll_live()
    assert requests[0][1]["capture_stopped"] is False
    window.network_result("LIVE", "test", dict(generation=generation, running=False,
                          waiting=True, reason="stopped", traces=[]))
    assert window.traces is traces and len(traces) == 2
    np.testing.assert_allclose(window.plot.viewRange(), ranges)
    assert window.math_group.isEnabled()


def test_space_in_text_editor_is_text_not_instrument_command(window):
    actions = []
    window.network = lambda action, values: actions.append(action)
    window.instrument_panel.update_settings(DATA)
    window.expression.setFocus()
    window.expression.setText("CH1")
    QtTest.QTest.keyClick(window.expression, QtCore.Qt.Key_Space)
    assert window.expression.text() == "CH1 "
    assert not actions
    assert not window.run_shortcut.autoRepeat()


def test_space_with_connection_button_focus_controls_instrument(window):
    actions = []
    window.network = lambda action, values: actions.append(action)
    window.instrument_panel.update_settings(DATA)
    window.live_enabled = True
    window.instrument_panel.set_live_state(True)
    window.instrument_panel.live_button.setFocus()
    QtTest.QTest.keyClick(window.instrument_panel.live_button, QtCore.Qt.Key_Space)
    assert actions == ["TOGGLE_RUN"]
    assert window.live_enabled


def test_two_queued_toggles_cancel_without_sending_after_transfer(window):
    window.instrument_panel.update_settings(DATA)
    window.live_enabled = True
    window.worker = object()  # Simulate an in-flight transfer at the queue boundary.
    try:
        window.queue_run_toggle()
        assert window._pending_run_toggle
        window.queue_run_toggle()
        assert not window._pending_run_toggle
        assert not window.instrument_panel._run_pending
    finally:
        window.worker = None


def test_run_control_does_not_replace_offline_unsaved_waveform(window, monkeypatch):
    window.set_traces([Trace("CH1", np.linspace(0, 1, 10), np.arange(10.))], "offline")
    window.dirty = True
    window.instrument_panel.update_settings(DATA)
    traces = window.traces
    monkeypatch.setattr(window, "confirm_replace", lambda: pytest.fail("RUN/STOP must not prompt to replace offline data"))
    window.worker = object()
    try:
        window.toggle_instrument()
        assert window._pending_run_toggle and not window.live_enabled
        assert window.traces is traces and window.dirty
    finally:
        window.worker = None
        window._pending_run_toggle = False


def test_single_after_stop_reads_a_new_frame_when_acquisition_completes(window):
    window.set_live(True)
    window._live_timer.stop()
    window._stopped_frame_valid = True
    window.network_result("SINGLE", "test", dict(DATA, running=True))
    assert not window._stopped_frame_valid
    requests = []
    window.network = lambda action, values: requests.append(values)
    window.poll_live()
    assert requests[0]["capture_stopped"] is True
