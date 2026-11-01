"""Validated front-panel settings for the DL1640 (IM701610-17E)."""
import math
import re

RECORD_LENGTHS = (1000, 10000, 100000, 1000000, 8000000)
HIGH_RES_RECORD_LENGTHS = (1000, 10000, 100000, 1000000, 4000000)


def scalar(text, unit=""):
    """Read decimal/scientific numbers and SI input such as 500mV or 2us."""
    match = re.fullmatch(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([GMkmunpµμ]?)\s*" + re.escape(unit) + r"\s*", str(text))
    if not match and unit:
        return scalar(text)
    if not match:
        raise ValueError(f"数値を確認してください: {text}（例: 0.001、1e-3、1m{unit}）")
    prefixes = {"G": 1e9, "M": 1e6, "k": 1e3, "": 1, "m": 1e-3,
                "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "n": 1e-9, "p": 1e-12}
    value = float(match[1]) * prefixes[match[2]]
    if not math.isfinite(value):
        raise ValueError("有限の数値を指定してください。")
    return value


def channel_number(value):
    if type(value) is not int or value not in (1, 2, 3, 4):
        raise ValueError("CHは1〜4の整数で指定してください。")
    return value


def settings_commands(group, values, fields=None):
    """Validate the entire group before any command is sent to the instrument."""
    if fields is not None:
        keys = {"time": ("tdiv", "acquire_mode", "record_length"),
                "channel": ("probe", "vdiv", "offset", "position", "coupling", "bandwidth", "invert", "display"),
                "trigger": ("trigger_mode", "source", "slope", "level", "delay")}
        if group not in keys or not fields or not set(fields) <= set(keys[group]):
            raise ValueError("変更項目の指定が不正です。")
        commands = settings_commands(group, values)
        names = {"tdiv": ":TIMEBASE:TDIV", "acquire_mode": ":ACQUIRE:MODE", "record_length": ":ACQUIRE:RLENGTH",
                 "trigger_mode": ":TRIGGER:MODE", "source": ":TRIGGER:SIMPLE:SOURCE",
                 "slope": ":TRIGGER:SIMPLE:SLOPE", "level": ":TRIGGER:SIMPLE:LEVEL", "delay": ":TRIGGER:DELAY"}
        if group == "channel":
            names.update({key: f":CHANNEL{values['channel']}:{command}" for key, command in {
                "probe": "PROBE", "vdiv": "VDIV", "offset": "OFFSET", "position": "POSITION", "coupling": "COUPLING",
                "bandwidth": "BWIDTH", "invert": "INVERT", "display": "DISPLAY"}.items()})
        selected = {names[key] for key in fields}
        if group == "trigger" and set(fields) & {"source", "slope", "level"}:
            selected.add(":TRIGGER:TYPE")
        return [cmd for cmd in commands if cmd.split(" ", 1)[0] in selected]

    def number(key, low, high, unit=""):
        if unit == "V|A":
            try:
                value = scalar(values[key], "V")
            except ValueError:
                value = scalar(values[key], "A")
        else:
            value = scalar(values[key], unit)
        if not low <= value <= high:
            raise ValueError(f"{key} は {low:g}〜{high:g} {unit} で指定してください。")
        return f"{value:.12g}"

    def choice(key, options):
        value = str(values[key]).upper()
        if value not in options:
            raise ValueError(f"{key} の選択値が不正です。")
        return value

    def boolean(key):
        if type(values[key]) is not bool:
            raise ValueError(f"{key} はON/OFFで指定してください。")
        return "ON" if values[key] else "OFF"

    if group == "time":
        record = scalar(values['record_length'])
        allowed = (HIGH_RES_RECORD_LENGTHS if values.get('_high_resolution') else RECORD_LENGTHS)
        if record not in allowed:
            raise ValueError("レコード長は " + ' / '.join(f'{n:g}' for n in allowed) + " 点から選択してください。")
        return [f":TIMEBASE:TDIV {number('tdiv', 2e-9, 800, 's')}",
                f":ACQUIRE:MODE {choice('acquire_mode', ('NORMAL', 'ENVELOPE', 'AVERAGE'))}",
                f":ACQUIRE:RLENGTH {int(record)}"]
    if group == "channel":
        ch = channel_number(values["channel"])
        prefix = f":CHANNEL{ch}:"
        probe = choice('probe', ('1', '10', '100', '1000', 'C10', 'C100'))
        unit = "A" if probe.startswith("C") else "V"
        # Probe first: sensitivity/offset values are expressed after probe scaling.
        return [prefix + "PROBE " + probe,
                prefix + "VDIV " + number('vdiv', 2e-3, 10000, unit),
                prefix + "OFFSET " + number('offset', -100000, 100000, unit),
                prefix + "POSITION " + number('position', -4, 4),
                prefix + "COUPLING " + choice('coupling', ('AC', 'DC', 'GND')),
                prefix + "BWIDTH " + choice('bandwidth', ('FULL', '20E6', '1.28E6', '640E3', '320E3', '160E3', '80E3', '20E3', '10E3')),
                prefix + "INVERT " + boolean('invert'),
                prefix + "DISPLAY " + boolean('display')]
    if group == "trigger":
        source = choice('source', ('1', '2', '3', '4', 'EXTERNAL', 'LINE'))
        commands = [":TRIGGER:TYPE SIMPLE",
                ":TRIGGER:MODE " + choice('trigger_mode', ('AUTO', 'ALEVEL', 'NORMAL', 'SINGLE', 'NSINGLE')),
                ":TRIGGER:SIMPLE:SOURCE " + source]
        if source != "LINE":
            commands += [":TRIGGER:SIMPLE:SLOPE " + choice('slope', ('RISE', 'FALL', 'BOTH')),
                         ":TRIGGER:SIMPLE:LEVEL " + number('level', -100000, 100000, 'V|A')]
        return commands + [":TRIGGER:DELAY " + number('delay', 0, 4, 's')]
    raise ValueError(f"未対応の設定グループ: {group}")
