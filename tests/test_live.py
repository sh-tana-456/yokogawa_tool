import numpy as np
import pytest
from yokogawa_tool.acquisition.instrument import ProtocolError
from test_instrument import FakeScope


class LiveScope(FakeScope):
    def __init__(self, running=False, broken=False, mode="AUTO"):
        super().__init__(running, broken)
        self.mode = mode

    def text(self, command):
        if command == ":TRIGGER:MODE?":
            return self.mode
        return super().text(command)

    def write(self, command):
        super().write(command)
        if command == ":STOP": self.running = False
        if command == ":START": self.running = True


@pytest.mark.parametrize("running", [False, True])
def test_live_snapshot_restores_acquisition_state(running):
    scope = LiveScope(running=running)
    result = scope.capture_live()
    assert result["running"] == running and not result["waiting"]
    assert len(result["traces"]) == 4
    assert scope.running == running
    if running:
        stop = scope.commands.index(":STOP")
        start = scope.commands.index(":START")
        assert stop > scope.commands.index(":WAVEFORM:FORMAT WORD")
        assert start > stop
        assert scope.commands[start+1:] == [f":WAVEFORM:{key} {value}" for key, value in
            (("TRACE", "1"), ("RECORD", "0"), ("START", "0"), ("END", "2"),
             ("DLENGTH", "AUTO"), ("FORMAT", "ASCII"), ("BYTEORDER", "LSBFIRST"))]
    else:
        assert ":STOP" not in scope.commands and ":START" not in scope.commands


def test_live_restarts_even_if_waveform_transfer_fails():
    scope = LiveScope(running=True, broken=True)
    with pytest.raises(ProtocolError):
        scope.capture_live()
    assert scope.running and ":START" in scope.commands
    assert scope.commands[-1] == ":WAVEFORM:BYTEORDER LSBFIRST"


@pytest.mark.parametrize("mode", ["SING", "SINGLE", "NSIN", "NSINGLE"])
def test_live_waits_for_single_acquisition_without_interrupting(mode):
    scope = LiveScope(running=True, mode=mode)
    result = scope.capture_live()
    assert result["waiting"] and not result["traces"]
    assert not scope.commands and scope.running


def test_live_readonly_probe_never_pauses_running_acquisition():
    scope = LiveScope(running=True)
    assert scope.capture_live(allow_pause=False)["waiting"]
    assert not scope.commands


def test_stopped_monitor_does_not_transfer_or_restart_after_final_frame():
    scope = LiveScope(running=False)
    result = scope.capture_live(capture_stopped=False)
    assert result == dict(waiting=True, running=False, traces=[], reason="stopped")
    assert scope.commands == []


def test_requested_stop_never_starts_an_already_finished_acquisition():
    scope = LiveScope(running=False)
    scope.read_settings = lambda channel: {"running": scope.running, "channel": channel}
    result = scope.set_running(False)
    assert not result["running"] and not scope.commands
    scope.running = True
    scope.control = lambda action: scope.write(":STOP" if action == "STOP" else ":START")
    scope.set_running(False)
    assert scope.commands == [":STOP"] and not scope.running


def test_live_prepares_while_running_and_decodes_after_resume(monkeypatch):
    import yokogawa_tool.acquisition.instrument as module
    scope = LiveScope(running=True)
    number = scope.number
    query = scope.query
    decode = module.decode_block
    def read_number(command):
        if command.startswith(":WAVEFORM:"):
            assert scope.running  # Metadata is no longer read inside the pause.
        return number(command)
    def send(command):
        assert not scope.running
        return query(command)
    def decode_after_start(message):
        assert scope.running
        return decode(message)
    scope.number = read_number
    scope.query = send
    monkeypatch.setattr(module, "decode_block", decode_after_start)
    result = scope.capture_live()
    assert result["pause_seconds"] >= 0 and len(result["traces"]) == 4


def test_live_reports_resume_failure_instead_of_claiming_run():
    scope = LiveScope(running=True)
    original = scope.write

    def write(command):
        if command == ":START":
            raise OSError("socket closed")
        original(command)

    scope.write = write
    with pytest.raises(ProtocolError, match="RUNへ戻せません"):
        scope.capture_live()
    assert not scope.running


def test_transfer_restore_error_is_reported_during_capture():
    scope = LiveScope(running=True)
    original_write, original_text = scope.write, scope.text
    errors = []

    def write(command):
        original_write(command)
        if command == ":WAVEFORM:FORMAT ASCII":
            errors.append('609,"Execution error;"')

    def text(command):
        if command == ":STATUS:ERROR?" and errors:
            return errors.pop(0)
        return original_text(command)

    scope.write, scope.text = write, text
    with pytest.raises(ProtocolError, match="波形取得・転送設定の復元.*609"):
        scope.capture_live()
    assert scope.running and not errors
    scope.control("STOP")
    assert not scope.running and not scope.control_warnings
