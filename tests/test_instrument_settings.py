import pytest
from yokogawa_tool.acquisition.instrument import DL1640, ProtocolError
from yokogawa_tool.acquisition.settings import scalar, settings_commands


CHANNEL = dict(channel=1, display=True, probe="10", vdiv="500mV", offset="0V",
               position="-3.5", coupling="DC", bandwidth="FULL", invert=False)
TIME = dict(channel=1, tdiv="2ms", acquire_mode="NORMAL", record_length="10000")
TRIGGER = dict(channel=1, trigger_mode="AUTO", source="3", slope="FALL", level="1V", delay="0s")


@pytest.mark.parametrize("text,unit,expected", [("2ms", "s", .002), ("10µs", "s", 1e-5),
    ("2e-9", "s", 2e-9), ("500mV", "V", .5), ("-3.5", "", -3.5)])
def test_settings_accept_scientific_and_si_input(text, unit, expected):
    assert scalar(text, unit) == pytest.approx(expected)


@pytest.mark.parametrize("text,unit", [("nan", ""), ("inf", ""), ("1e999", ""),
    ("1;:START", ""), ("1ms", "V"), ("1V", "s")])
def test_settings_reject_nonfinite_wrong_units_and_command_injection(text, unit):
    with pytest.raises(ValueError):
        scalar(text, unit)


class SettingsScope(DL1640):
    def __init__(self, errors=()):
        super().__init__("test")
        self.commands = []
        self.queries = []
        self.errors = iter(errors)
        self.responses = {"*IDN?": "YOKOGAWA,701610,0,F1.08", ":STATUS:CONDITION?": "0",
            ":TIMEBASE:TDIV?": ".002", ":TIMEBASE:SRATE?": "1e6", ":ACQUIRE:RLENGTH?": "10000", ":ACQUIRE:MODE?": "NORM", ":ACQUIRE:RESOLUTION?": "0",
            ":TRIGGER:MODE?": "AUTO", ":TRIGGER:TYPE?": "SIMP", ":TRIGGER:DELAY?": "0",
            ":TRIGGER:SIMPLE:SOURCE?": "3", ":TRIGGER:SIMPLE:SLOPE?": "FALL", ":TRIGGER:SIMPLE:LEVEL?": "1"}
        self.responses.update({f":CHANNEL1:{key}?": value for key, value in dict(DISPLAY="1", PROBE="10",
            VDIV=".5", OFFSET="0", POSITION="-3.5", COUPLING="DC", BWIDTH="FULL", INVERT="0").items()})

    def text(self, command):
        self.queries.append(command)
        if command == ":STATUS:ERROR?":
            return next(self.errors, '0,"No error"')
        return self.responses[command]

    def write(self, command):
        self.commands.append(command)


def test_read_settings_never_writes_instrument_configuration():
    scope = SettingsScope()
    data = scope.read_settings(1)
    assert data["vdiv"] == ".5" and data["trigger_mode"] == "AUTO"
    assert data["running"] is False
    assert not scope.commands
    scope.responses[":TRIGGER:SIMPLE:SOURCE?"] = "LINE"
    scope.queries.clear()
    data = scope.read_settings(1)
    assert "level" not in data and "slope" not in data
    assert ":TRIGGER:SIMPLE:LEVEL?" not in scope.queries


@pytest.mark.parametrize("group,values", [("time", TIME), ("channel", CHANNEL), ("trigger", TRIGGER)])
def test_apply_checks_errors_and_reads_actual_values(group, values):
    scope = SettingsScope()
    actual = scope.apply_settings(group, values)
    assert scope.commands == settings_commands(group, values)
    assert scope.queries.count(":STATUS:ERROR?") == len(scope.commands)+1
    assert actual["vdiv"] == ".5"
    if group == "channel":
        assert scope.commands[:2] == [":CHANNEL1:PROBE 10", ":CHANNEL1:VDIV 0.5"]


@pytest.mark.parametrize("group,values,key,bad", [("time", TIME, "tdiv", "1ns"),
    ("time", TIME, "record_length", "1000.5"), ("time", TIME, "record_length", "9000000"),
    ("channel", CHANNEL, "channel", "1;:START"), ("channel", CHANNEL, "position", "5"),
    ("channel", CHANNEL, "vdiv", "nan"), ("channel", CHANNEL, "display", "ON"),
    ("trigger", TRIGGER, "delay", "-1ms"), ("trigger", TRIGGER, "slope", "RISE;:START")])
def test_invalid_group_is_rejected_before_any_io(group, values, key, bad):
    scope = SettingsScope()
    with pytest.raises(ValueError):
        scope.apply_settings(group, dict(values, **{key: bad}))
    assert not scope.commands and not scope.queries


def test_device_error_stops_partial_apply_and_reports_command():
    scope = SettingsScope(errors=['0,"No error"', '113",Undefined header"'])
    with pytest.raises(ProtocolError, match=":TIMEBASE:TDIV"):
        scope.apply_settings("time", TIME)
    assert len(scope.commands) == 1
    scope = SettingsScope(errors=['222,"Old error"'])
    with pytest.raises(ProtocolError, match="設定変更前"):
        scope.apply_settings("time", TIME)
    assert not scope.commands


@pytest.mark.parametrize('value', ('5k', '20k', '200k', '2M'))
def test_unsupported_record_lengths_rejected_before_io(value):
    scope = SettingsScope()
    with pytest.raises(ValueError, match='レコード長'):
        scope.apply_settings('time', dict(TIME, record_length=value), ['record_length'])
    assert not scope.commands and not scope.queries


def test_record_length_fixed_choices_and_high_resolution_limit():
    for value in ('1k', '10k', '100k', '1M', '8M'):
        assert settings_commands('time', dict(TIME, record_length=value), ['record_length']) == [
            f':ACQUIRE:RLENGTH {int(scalar(value))}']
    assert settings_commands('time', dict(TIME, record_length='4M', _high_resolution=True), ['record_length']) == [':ACQUIRE:RLENGTH 4000000']
    with pytest.raises(ValueError):
        settings_commands('time', dict(TIME, record_length='8M', _high_resolution=True))


def test_record_length_preserves_stop_after_firmware_autostart():
    class AutoStartScope(SettingsScope):
        def write(self, command):
            super().write(command)
            if command.startswith(':ACQUIRE:RLENGTH '):
                self.responses[':ACQUIRE:RLENGTH?'] = command.split()[-1]
                self.responses[':STATUS:CONDITION?'] = '1'
            elif command == ':STOP':
                self.responses[':STATUS:CONDITION?'] = '0'
    scope = AutoStartScope()
    actual = scope.apply_settings('time', dict(TIME, record_length='1k', _high_resolution=True), ['record_length'])
    assert not actual['running']
    assert scope.commands == [':ACQUIRE:RLENGTH 1000', ':STOP']
    scope = AutoStartScope()
    scope.responses[':STATUS:CONDITION?'] = '1'
    actual = scope.apply_settings('time', TIME, ['record_length'])
    assert actual['running']
    assert ':STOP' not in scope.commands


def test_single_start_order_and_error_abort():
    scope = SettingsScope()
    scope.control("SINGLE")
    assert scope.commands == [":TRIGGER:MODE SINGLE", ":START"]
    scope = SettingsScope(errors=['0,"No error"', '222,"Out of range"'])
    with pytest.raises(ProtocolError):
        scope.control("SINGLE")
    assert scope.commands == [":TRIGGER:MODE SINGLE"]


def test_run_separates_all_old_errors_from_current_command(caplog):
    scope = SettingsScope(errors=['609,"Execution error;"', '812,"Execution error;"',
                                  '0,"No error"', '0,"No error"'])
    result = scope.set_running(True)
    assert scope.commands == [":START"]
    assert len(result["warnings"]) == 2
    assert "609" in caplog.text and "812" in caplog.text


def test_real_start_error_still_fails_and_drains_following_errors():
    scope = SettingsScope(errors=['0,"No error"', '609,"Execution error;"',
                                  '812,"Execution error;"', '0,"No error"'])
    with pytest.raises(ProtocolError, match=":START") as error:
        scope.set_running(True)
    assert "609" in str(error.value) and "812" in str(error.value)
    assert "設定を再読込" not in str(error.value)
    scope.control("STOP")  # The previous error must not be blamed on STOP.
    assert not scope.control_warnings


def test_error_queue_limit_and_malformed_response():
    for errors in (['609,"Execution error;"'] * 100, ["invalid"]):
        scope = SettingsScope(errors=errors)
        with pytest.raises(ProtocolError):
            scope.control("RUN")
        assert not scope.commands


def test_line_trigger_omits_unsupported_level_and_slope():
    commands = settings_commands("trigger", dict(TRIGGER, source="LINE", level="", slope=""))
    assert ":TRIGGER:SIMPLE:SOURCE LINE" in commands
    assert not any(":LEVEL" in cmd or ":SLOPE" in cmd for cmd in commands)


def test_current_probe_units():
    commands = settings_commands("channel", dict(CHANNEL, probe="C10", vdiv="5mA", offset="0A"))
    assert ":CHANNEL1:VDIV 0.005" in commands
    commands = settings_commands("trigger", dict(TRIGGER, level="5mA"))
    assert ":TRIGGER:SIMPLE:LEVEL 0.005" in commands


def test_auto_setup_waits_for_completion():
    scope = SettingsScope()
    scope.responses["*OPC?"] = "1"
    scope.control("AUTO_SETUP")
    assert scope.commands == [":ASETUP:EXECUTE"]
    assert scope.queries == [":STATUS:ERROR?", "*OPC?", ":STATUS:ERROR?"]


def test_partial_sync_writes_only_edited_fields():
    scope = SettingsScope()
    scope.apply_settings("channel", dict(CHANNEL, offset="100mV"), fields=["offset"])
    assert scope.commands == [":CHANNEL1:OFFSET 0.1"]
    scope = SettingsScope()
    scope.apply_settings("trigger", TRIGGER, fields=["trigger_mode"])
    assert scope.commands == [":TRIGGER:MODE AUTO"]
    scope = SettingsScope()
    scope.apply_settings("trigger", TRIGGER, fields=["level"])
    assert scope.commands == [":TRIGGER:TYPE SIMPLE", ":TRIGGER:SIMPLE:LEVEL 1"]


@pytest.mark.parametrize("running,command", [("0", ":START"), ("1", ":STOP")])
def test_toggle_uses_actual_instrument_state(running, command):
    scope = SettingsScope()
    scope.responses[":STATUS:CONDITION?"] = running
    scope.toggle_run()
    assert scope.commands == [command]
    assert scope.queries[0] == ":STATUS:CONDITION?"


def test_invalid_patch_is_rejected_before_io():
    scope = SettingsScope()
    with pytest.raises(ValueError):
        scope.apply_settings("channel", CHANNEL, fields=["offset;:START"])
    with pytest.raises(ValueError):
        scope.toggle_run("1;:STOP")
    assert not scope.commands and not scope.queries
