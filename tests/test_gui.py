"""Offscreen integration tests exercise plotting, cursor readout and portability."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from PySide6 import QtCore, QtGui, QtTest
from yokogawa_tool.gui.app import MainWindow, configure_application
from yokogawa_tool.core.waveform import load_session, save_session


@pytest.fixture(scope="module")
def application():
    app = QApplication.instance() or QApplication([])
    configure_application(app)
    yield app


def test_wvf_export_dialog_preserves_session_and_checks_companion(application, tmp_path, monkeypatch):
    from PySide6 import QtWidgets as W
    from yokogawa_tool.core.waveform import read_wvf
    window = MainWindow()
    window.error = lambda message: pytest.fail(str(message))
    window.open_path(Path(__file__).resolve().parents[1] / "demo/0000.WVF")
    window.expression.setText("CH1 - CH2")
    window.add_expression()
    assert window.dirty
    target = tmp_path / "output.wvf"
    header = tmp_path / "output.hdr"
    header.write_bytes(b"existing header")
    monkeypatch.setattr(W.QFileDialog, "getSaveFileName", lambda *a, **kw: (str(target), ""))
    prompts = []
    def decline(*args):
        prompts.append(args[2])
        return W.QMessageBox.StandardButton.No
    monkeypatch.setattr(W.QMessageBox, "question", decline)
    window.wvf_dialog()
    assert str(header) in prompts[0] and not target.exists()
    assert header.read_bytes() == b"existing header"
    monkeypatch.setattr(W.QMessageBox, "question", lambda *a: W.QMessageBox.StandardButton.Yes)
    window.wvf_dialog()
    restored = read_wvf(target)
    assert len(restored) == 4
    np.testing.assert_array_equal(restored[-1].y, window.traces[-1].y)
    assert window.dirty  # An interchange export must not mark the session saved.
    assert window.file_actions["WVF/HDR出力"].shortcut().toString() == "Ctrl+Shift+E"
    window.mode_tabs.setCurrentIndex(1)
    assert not window.file_actions["WVF/HDR出力"].isEnabled()
    window.mode_tabs.setCurrentIndex(0)
    assert window.file_actions["WVF/HDR出力"].isEnabled()
    window.dirty = False
    window.close()


def test_open_zoom_cursors_math_session(application, tmp_path):
    window = MainWindow()
    window.show()
    window.open_path(Path(__file__).resolve().parents[1] / "demo/0000.WVF")
    application.processEvents()
    assert len(window.curves) == 3
    assert window.table.rowCount() == 3
    window.cursor_a.setValue(-.001)
    window.cursor_b.setValue(.002)
    window.zoom_cursors()
    np.testing.assert_allclose(window.plot.viewRange()[0], [-.001, .002])
    window.expression.setText("CH1 - CH2")
    window.add_expression()
    np.testing.assert_allclose(window.traces[-1].y, window.traces[0].y - window.traces[1].y)
    window.toggle_trace(window.traces[1], False)
    assert len(window.curves) == 3
    path = tmp_path / "session.scope.npz"
    save_session(path, window.traces, window.view_state())
    traces, view = load_session(path)
    restored = MainWindow()
    restored.set_traces(traces, "restored", view)
    assert not restored.traces[1].visible
    assert restored.cursor_a.value() == -.001
    np.testing.assert_allclose(restored.plot.viewRange()[0], [-.001, .002])
    assert restored.table.rowCount() == 4
    window.dirty = restored.dirty = False
    window.close()
    restored.close()


def test_automatic_edits_and_run_toggle_through_worker(application, waveform_window, monkeypatch):
    from test_panel_sync import DATA
    import yokogawa_tool.gui.app as module
    calls = []
    actual = dict(DATA)

    class Backend:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read_settings(self, channel): return dict(actual, channel=channel)
        def apply_settings(self, group, values, fields=None):
            calls.append((group, fields))
            actual.update({key: values[key] for key in fields})
            return self.read_settings(values["channel"])
        def set_running(self, running, channel):
            actual["running"] = running
            return self.read_settings(channel)

    monkeypatch.setattr(module, "DL1640", Backend)
    window = waveform_window
    panel = window.instrument_panel
    window.network("READ_SETTINGS", {"channel": 1})
    for _ in range(100):
        QtTest.QTest.qWait(10)
        if window.worker is None: break
    assert panel._loaded
    panel.fields["offset"].plus.click()
    QtTest.QTest.qWait(350)
    for _ in range(100):
        QtTest.QTest.qWait(10)
        if window.worker is None: break
    assert calls == [("channel", ["offset"])]
    assert panel.fields["offset"].value() == pytest.approx(.05)
    panel.run_button.click()
    for _ in range(100):
        QtTest.QTest.qWait(10)
        if window.worker is None: break
    assert panel.running is True and panel.run_button.property("role") == "stop"


def test_zoom_coalesces_measurements_and_reuses_table_items(application, waveform_window):
    from yokogawa_tool.gui.app import fmt
    window = waveform_window
    item = window.table.item(0, 9)
    for i in range(20):
        window.plot.setXRange(-.002+i*1e-5, .002-i*1e-5, padding=0)
    assert window._readout_timer.isActive()
    assert window.table.item(0, 9) is item
    QtTest.QTest.qWait(100)
    assert not window._readout_timer.isActive()
    assert window.table.item(0, 9) is item
    t = window.traces[0]
    lo, hi = window.plot.viewRange()[0]
    y = t.y[np.searchsorted(t.x, lo):np.searchsorted(t.x, hi, side="right")]
    assert item.text() == fmt(np.nanmean(y), t.unit)


def test_live_theme_switch_preserves_waveforms(application):
    window = MainWindow()
    original = window.theme_combo.currentData()
    window.open_path(Path(__file__).resolve().parents[1] / "demo/0000.WVF")
    data = window.traces[0].y.copy()
    color = window.traces[0].color
    for name in ("xp", "light", "dark"):
        window.apply_theme(name)
        application.processEvents()
        assert window.theme_combo.currentData() == name
        assert window.plot.backgroundBrush().color().name() == ("#101720" if name == "dark" else "#ffffff")
        np.testing.assert_array_equal(window.traces[0].y, data)
        assert window.traces[0].color == color
    window.apply_theme(original)
    window.dirty = False
    window.close()


@pytest.fixture
def waveform_window(application):
    window = MainWindow()
    original_axis = window.wheel_axis_combo.currentIndex()
    window.show()
    window.open_path(Path(__file__).resolve().parents[1] / "demo/0000.WVF")
    application.processEvents()
    yield window
    window.wheel_axis_combo.setCurrentIndex(original_axis)
    window.dirty = False
    window.close()


def send_wheel(application, plot, delta, x=None):
    view = plot.getViewBox()
    scene_pos = (view.mapViewToScene(QtCore.QPointF(x, sum(view.viewRange()[1])/2))
                 if x is not None else view.sceneBoundingRect().center())
    local = QtCore.QPointF(plot.mapFromScene(scene_pos))
    event = QtGui.QWheelEvent(local, QtCore.QPointF(plot.viewport().mapToGlobal(local.toPoint())),
        QtCore.QPoint(), QtCore.QPoint(0, delta), QtCore.Qt.NoButton,
        QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False)
    QApplication.sendEvent(plot.viewport(), event)
    application.processEvents()
    assert event.isAccepted()


@pytest.mark.parametrize("axis", [0, 1])
def test_wheel_changes_only_selected_axis(application, waveform_window, axis):
    window = waveform_window
    window.wheel_axis_combo.setCurrentIndex(axis)
    before = np.array(window.plot.viewRange())
    send_wheel(application, window.plot, 120)
    after = np.array(window.plot.viewRange())
    other = 1-axis
    np.testing.assert_allclose(after[other], before[other], atol=1e-12)
    assert np.ptp(after[axis]) < np.ptp(before[axis])
    np.testing.assert_allclose(window.region.getRegion(), after[0])
    send_wheel(application, window.plot, -120)
    restored = np.array(window.plot.viewRange())
    np.testing.assert_allclose(restored[other], before[other], atol=1e-12)
    np.testing.assert_allclose(np.ptp(restored[axis]), np.ptp(before[axis]), rtol=1e-8)
    # Tick-label reflow can shift the viewport's pixel center between events.
    pixels = window.plot.getViewBox().width() if axis == 0 else window.plot.getViewBox().height()
    assert abs(restored[axis].mean()-before[axis].mean()) < np.ptp(before[axis])*2/pixels
    # Selecting the wheel axis must leave drag/rectangle navigation on both axes.
    assert window.plot.getViewBox().mouseEnabled() == [True, True]


@pytest.mark.parametrize("inside_selection", [False, True])
def test_overview_wheel_zooms_time_selection_only(application, waveform_window, inside_selection):
    window = waveform_window
    window.wheel_axis_combo.setCurrentIndex(1)
    window.plot.setRange(xRange=(-.001, .001), yRange=(-1, 4), padding=0)
    application.processEvents()
    overview_before = np.array(window.overview.viewRange())
    main_before = np.array(window.plot.viewRange())
    # Exercise both the region item and the area outside it.
    anchor = 0 if inside_selection else .003
    send_wheel(application, window.overview, 120, x=anchor)
    after = np.array(window.plot.viewRange())
    assert np.ptp(after[0]) < np.ptp(main_before[0])
    np.testing.assert_allclose(after[1], main_before[1])
    np.testing.assert_allclose(window.overview.viewRange(), overview_before)
    np.testing.assert_allclose(window.region.getRegion(), after[0])
    send_wheel(application, window.overview, -120, x=anchor)
    np.testing.assert_allclose(window.plot.viewRange(), main_before, rtol=1e-8, atol=1e-12)


def test_sidebar_can_be_hidden_and_reopened(application, waveform_window):
    window = waveform_window
    before = window.plot.width()
    assert window.sidebar_dock.isVisible()
    window.sidebar_action.trigger()
    application.processEvents()
    assert not window.sidebar_dock.isVisible()
    assert window.plot.width() > before
    window.sidebar_action.trigger()
    application.processEvents()
    assert window.sidebar_dock.isVisible()
    assert len(window.curves) == 3


def test_wheel_axis_preference_is_restored(waveform_window):
    window = waveform_window
    window.wheel_axis_combo.setCurrentIndex(1)
    restored = MainWindow()
    assert restored.wheel_axis_combo.currentData() == "y"
    assert restored.plot.getViewBox().wheel_axis == 1
    restored.close()


def test_antialias_changes_rendering_without_altering_samples(application, waveform_window):
    window = waveform_window
    original = window.antialias_checkbox.isChecked()
    window.plot.setRange(xRange=(-.001, .001), yRange=(-.5, 4), padding=0)
    x, y = window.traces[0].x.copy(), window.traces[0].y.copy()
    images = []
    for enabled in (False, True):
        window.antialias_checkbox.setChecked(enabled)
        application.processEvents()
        image = window.plot.grab().toImage().convertToFormat(QtGui.QImage.Format_RGBA8888)
        images.append(bytes(image.constBits()))
        np.testing.assert_array_equal(window.traces[0].x, x)
        np.testing.assert_array_equal(window.traces[0].y, y)
        np.testing.assert_array_equal(window.curves[0].yData, y)
        assert window.curves[0].curve.opts["antialias"] == enabled
    assert images[0] != images[1]
    window.antialias_checkbox.setChecked(original)


def test_instrument_tab_and_apply_payload(application, waveform_window):
    window = waveform_window
    panel = window.instrument_panel
    assert window.sidebar_tabs.tabText(1) == "実機操作"
    assert not panel.fields["offset"].isEnabled()
    data = dict(identity="YOKOGAWA,701610,0,F1.08", running=False, channel=1,
        tdiv=".002", record_length="10000", acquire_mode="NORM", trigger_mode="AUTO", trigger_type="SIMP",
        display="1", probe="10", vdiv=".5", offset="0", position="-3.5", coupling="DC", bandwidth="FULL",
        invert="0", source="3", slope="FALL", level="1", delay="0")
    window.network_result("READ_SETTINGS", panel.host.text(), data)
    assert panel.fields["acquire_mode"].currentData() == "NORMAL"
    assert panel.fields["offset"].isEnabled()
    # Capture the UI request independently of real networking.
    panel.requested.disconnect(window.network)
    requests = []
    panel.requested.connect(lambda action, values: requests.append((action, values)))
    panel.fields["vdiv"].setText("200mV")
    assert not requests
    panel.fields["vdiv"].editor.setText("100mV")
    panel.fields["vdiv"].commit()
    assert not requests
    panel.sync_timer.stop()
    panel.flush_pending()
    assert requests[0][0] == "APPLY_CHANNEL"
    assert requests[0][1]["vdiv"] == "100mV" and requests[0][1]["channel"] == 1
    assert requests[0][1]["_fields"] == ["vdiv"]
    panel.set_busy(False)
    panel.channel.setCurrentIndex(1)
    assert not panel.fields["offset"].isEnabled()
    panel.host.setText("10.0.10.17")
    assert not panel.fields["tdiv"].isEnabled()
    assert len(window.curves) == 3
