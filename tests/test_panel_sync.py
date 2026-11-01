import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import pytest
from PySide6 import QtCore, QtWidgets as W, QtTest
from yokogawa_tool.gui.instrument_panel import InstrumentPanel
from yokogawa_tool.acquisition.settings import scalar


DATA = dict(identity="YOKOGAWA,701610,0,F1.08", running=False, channel=1,
    tdiv=".002", record_length="10000", acquire_mode="NORM", trigger_mode="AUTO", trigger_type="SIMP",
    display="1", probe="10", vdiv=".5", offset="0", position="-3.5", coupling="DC", bandwidth="FULL",
    invert="0", source="3", slope="FALL", level="1", delay="0")


@pytest.fixture
def panel(tmp_path):
    app = W.QApplication.instance() or W.QApplication([])
    settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.IniFormat)
    widget = InstrumentPanel(settings)
    widget.update_settings(DATA)
    requests = []
    widget.requested.connect(lambda action, values: requests.append((action, values)))
    yield widget, requests
    widget.invalidate()
    widget.close()


def test_offset_buttons_and_fine_adjustment(panel):
    widget, requests = panel
    offset = widget.fields["offset"]
    offset.plus.click()
    offset.plus.click()
    assert offset.value() == pytest.approx(.1)
    assert not requests
    widget.fine.setChecked(True)
    offset.minus.click()
    assert offset.value() == pytest.approx(.095)
    QtTest.QTest.qWait(300)
    assert len(requests) == 1
    assert requests[0][0] == "APPLY_CHANNEL"
    assert requests[0][1]["_fields"] == ["offset"]
    assert scalar(requests[0][1]["offset"]) == pytest.approx(.095)


def test_engineering_steps_and_limits(panel):
    widget, _ = panel
    sensitivity = widget.fields["vdiv"]
    sensitivity.plus.click()
    assert sensitivity.value() == 1
    sensitivity.plus.click()
    assert sensitivity.value() == 2
    sensitivity.minus.click()
    assert sensitivity.value() == 1
    position = widget.fields["position"]
    position.setText("4")
    position.plus.click()
    assert position.value() == 4
    position.minus.click()
    assert position.value() == pytest.approx(3.9)


def test_record_length_selector_matches_hardware_and_readback_does_not_resend(panel):
    widget, requests = panel
    choice = widget.fields['record_length']
    assert not choice.isEditable()
    assert [choice.itemText(i) for i in range(choice.count())] == ['1k', '10k', '100k', '1M', '8M']
    assert choice.findData('5000') == -1 and choice.findData('20000') == -1
    choice.setCurrentIndex(choice.findData('100000'))
    widget.sync_timer.stop(); widget.flush_pending()
    assert requests[-1][0] == 'APPLY_TIME'
    assert requests[-1][1]['record_length'] == '100000'
    requests.clear()
    widget.update_settings(dict(DATA, high_resolution='1', record_length='4000000'))
    assert choice.currentData() == '4000000'
    assert choice.findData('8000000') == -1
    widget.sync_timer.stop(); widget.flush_pending()
    assert not requests


def test_inflight_readback_preserves_newer_edits_and_queues_latest(panel):
    widget, requests = panel
    offset = widget.fields["offset"]
    offset.plus.click()
    widget.sync_timer.stop()
    widget.flush_pending()
    widget.set_busy(True)
    assert scalar(requests[0][1]["offset"]) == pytest.approx(.05)
    # More adjustments while the first network operation is in flight.
    offset.plus.click()
    offset.plus.click()
    assert offset.value() == pytest.approx(.15)
    widget.update_settings(dict(DATA, offset=".05"))
    assert offset.value() == pytest.approx(.15)
    widget.flush_pending()
    assert len(requests) == 1
    widget.set_busy(False)
    QtTest.QTest.qWait(20)
    assert len(requests) == 2
    assert scalar(requests[-1][1]["offset"]) == pytest.approx(.15)
    # A later fresh edit must still debounce; start(0) must not persist.
    widget.update_settings(dict(DATA, offset=".15"))
    widget.set_busy(False)
    offset.plus.click()
    assert widget.sync_timer.interval() == 250


def test_readback_does_not_commit_unfinished_typing(panel):
    widget, requests = panel
    editor = widget.fields["offset"].editor
    editor.setText(".125")
    editor.setModified(True)
    widget.update_settings(dict(DATA, offset=".05"))
    assert editor.text() == ".125" and editor.isModified()
    widget.fields["offset"].commit()
    widget.sync_timer.stop()
    widget.flush_pending()
    assert requests[-1][1]["offset"] == ".125"


def test_run_stop_is_one_confirmed_state_toggle(panel):
    widget, requests = panel
    assert widget.run_button.isEnabled() and not widget.run_button.isChecked()
    assert "RUN" in widget.run_button.text()
    assert widget.run_button.property("role") == "run"
    widget.run_button.click()
    assert requests[-1][0] == "TOGGLE_RUN"
    assert not widget.run_button.isChecked()  # Wait for actual device state.
    widget.update_settings(dict(DATA, running=True))
    assert widget.run_button.isChecked() and "STOP" in widget.run_button.text()
    assert widget.run_button.property("role") == "stop"
    widget.run_button.click()
    assert widget.run_button.isChecked()
    assert requests[-1][0] == "TOGGLE_RUN"


def test_readback_does_not_echo_and_channel_selection_auto_refreshes(panel):
    widget, requests = panel
    widget.update_settings(DATA)
    QtTest.QTest.qWait(280)
    assert not requests
    widget.channel.setCurrentIndex(1)
    QtTest.QTest.qWait(300)
    assert requests == [("READ_SETTINGS", {"channel": 2})]
    assert not widget.fields["offset"].isEnabled()


def test_channel_selection_stays_available_during_live_read_and_is_queued(panel):
    widget, requests = panel
    widget.set_busy(True)
    assert widget.channel.isEnabled() and not widget.host.isEnabled()
    widget.channel.setCurrentIndex(2)
    widget.flush_pending()
    assert not requests and widget._refresh_requested
    widget.update_settings(DATA)  # An older CH1 response must not undo CH3 choice.
    assert widget.channel.currentData() == 3 and widget._refresh_requested
    widget.set_busy(False)
    widget.sync_timer.stop()
    widget.flush_pending()
    assert requests == [("READ_SETTINGS", {"channel": 3})]


def test_manual_lcd_request_is_queued_during_transfer(panel):
    widget, requests = panel
    widget.set_busy(True)
    widget.command('LCD_ON')
    widget.flush_pending()
    assert not requests and not widget.blank_display.isChecked()
    widget.set_busy(False)
    widget.sync_timer.stop()
    widget.flush_pending()
    assert requests == [('LCD', {'enabled': True})]


def test_invalid_edit_never_sends_or_restarts(panel):
    widget, requests = panel
    widget.fields["offset"].editor.setText("nan")
    widget.fields["offset"].commit()
    QtTest.QTest.qWait(300)
    assert not requests
    assert "入力値" in widget.status.text()


def test_status_message_changes_keep_panel_geometry(panel):
    widget, _ = panel
    scroll = W.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(widget)
    scroll.resize(350, 700)
    scroll.show()
    W.QApplication.processEvents()
    assert scroll.horizontalScrollBar().maximum() == 0
    status_geometry = widget.status.geometry()
    controls_y = widget.controls.y()
    for text in ("接続中", "YOKOGAWA,701610,0,F1.08\n停止中 · CH1の設定を読込",
                 "設定を適用し、本体の実値を読込済み\n" * 10, "長い接続先" * 80):
        widget.status.setText(text)
        W.QApplication.processEvents()
        assert widget.status.geometry() == status_geometry
        assert widget.controls.y() == controls_y
        assert widget.status.toolTip() == text
    scroll.takeWidget()
    scroll.close()
