"""Legacy Yokogawa TCP framing (port 10001), independent of Windows/TMCTL."""
import socket
import struct
import time
import re
import logging
import numpy as np
from yokogawa_tool.core.waveform import Trace, COLORS
from yokogawa_tool.acquisition.settings import channel_number, settings_commands


class ProtocolError(RuntimeError):
    pass


class DL1640:
    MAX_MESSAGE = 128 * 1024 * 1024

    def __init__(self, host, port=10001, username="anonymous", password="", timeout=8):
        self.host, self.port = host, int(port)
        self.username, self.password = username, password
        self.timeout = timeout
        self.socket = None
        self.control_warnings = []
        self._original_display = None
        self.display_restore_error = None

    def __enter__(self):
        try:
            self.socket = socket.create_connection((self.host, self.port), self.timeout)
            if b"username" not in self._nonempty().lower():
                raise ProtocolError("ユーザー名プロンプトを受信できませんでした。")
            self._send(self.username.encode("ascii"))
            if b"password" not in self._nonempty().lower():
                raise ProtocolError("ユーザー認証に失敗しました。")
            self._send(self.password.encode("ascii"))
            if b"ready" not in self._nonempty().lower():
                raise ProtocolError("ログインに失敗しました。Remote Cntlのユーザー設定を確認してください。")
            return self
        except Exception:
            self.close()
            raise

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self.socket:
            timeout = self.timeout
            try:
                self.timeout = min(timeout, 1.)
                self.restore_display()
            except Exception as exc:
                self.display_restore_error = f"本体LCDの復元に失敗しました。本体で表示状態を確認してください: {exc}"
                logging.getLogger(__name__).warning(self.display_restore_error)
            finally:
                self.timeout = timeout
                self.socket.close()
                self.socket = None

    def set_display_blanked(self, enabled):
        if not enabled:
            self.restore_display()
        elif self._original_display is None:
            self.archive_errors("LCD操作前")
            original = bool(int(self.number(":SYSTEM:LCD:MODE?")))
            # Save before writing so a failed command still gets a restoration attempt.
            self._original_display = original
            if original:
                self.write_checked(":SYSTEM:LCD:MODE OFF")

    def restore_display(self):
        if self._original_display is not None:
            original = self._original_display
            self.archive_errors("LCD復元前")
            self.write_checked(f":SYSTEM:LCD:MODE {'ON' if original else 'OFF'}")
            self._original_display = None

    def configure_lcd(self, enabled=None, brightness=None):
        if enabled is not None and type(enabled) is not bool:
            raise ValueError('LCDのON/OFFは真偽値で指定してください。')
        if brightness is not None and (type(brightness) is not int or not 1 <= brightness <= 4):
            raise ValueError('LCDの明るさは1〜4です。')
        self.archive_errors('LCD手動操作前')
        if enabled is not None:
            self.restore_display()
            self.write_checked(':SYSTEM:LCD:MODE ' + ('ON' if enabled else 'OFF'))
        if brightness is not None:
            self.write_checked(f':SYSTEM:LCD:BRIGHTNESS {brightness}')
        return {'lcd_on': bool(int(self.number(':SYSTEM:LCD:MODE?'))),
                'lcd_brightness': int(self.number(':SYSTEM:LCD:BRIGHTNESS?'))}

    def _exact(self, size):
        chunks = bytearray()
        while len(chunks) < size:
            data = self.socket.recv(min(size - len(chunks), 65536))
            if not data:
                raise ProtocolError("DL1640が接続を終了しました。認証・Network設定を確認してください。")
            chunks.extend(data)
        return bytes(chunks)

    def _receive(self):
        data = bytearray()
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                self.socket.settimeout(max(0.001, deadline - time.monotonic()))
                header = struct.unpack(">I", self._exact(4))[0]
                size = header & 0x7fffffff
                if len(data) + size > self.MAX_MESSAGE:
                    raise ProtocolError("通信データがサイズ上限を超えました。")
                data.extend(self._exact(size))
                if header & 0x80000000:
                    return bytes(data)
                if time.monotonic() >= deadline:
                    raise TimeoutError("受信がタイムアウトしました。")
        finally:
            self.socket.settimeout(self.timeout)

    def _nonempty(self):
        for _ in range(8):
            data = self._receive()
            if data:
                return data
        raise ProtocolError("有効な応答がありません。")

    def _send(self, data):
        self.socket.sendall(struct.pack(">I", 0x80000000 | len(data)) + data)

    def write(self, command):
        self._send(command.encode("ascii"))
        ack = self._receive()
        if ack.strip():
            raise ProtocolError(f"コマンド応答が不正です: {ack[:200]!r}")

    def query(self, command):
        self._send(command.encode("ascii"))
        return self._nonempty()

    def text(self, command):
        text = self.query(command).decode("ascii").strip()
        # Support both header-enabled and header-disabled instruments.
        return text.split(None, 1)[-1] if text.startswith(":") else text

    def number(self, command):
        return float(self.text(command))

    def identify(self):
        return self.text("*IDN?")

    def control(self, action):
        commands = {"RUN": [":START"], "STOP": [":STOP"], "LOCAL": [":COMMUNICATE:REMOTE OFF"],
                    "SINGLE": [":TRIGGER:MODE SINGLE", ":START"], "AUTO_SETUP": [":ASETUP:EXECUTE"]}[action]
        # ERROR? returns the oldest queued error, not the result of the last write.
        # Keep old errors visible in the log, without treating them as START failure.
        self.control_warnings = self.archive_errors(f"{action}操作前") if action != "LOCAL" else []
        for command in commands:
            if action == "LOCAL":
                self.write(command)
            elif action == "AUTO_SETUP":
                self.write(command)
                self.text("*OPC?")
                self.check_error(command)
            else:
                self.write_checked(command)
        return f"{action}を送信しました。"

    def write_checked(self, command):
        self.write(command)
        self.check_error(command)

    def read_errors(self):
        errors = []
        for _ in range(100):
            response = self.text(":STATUS:ERROR?")
            match = re.match(r"^\s*([+-]?\d+)\b", response)
            if not match:
                raise ProtocolError(f"実機のエラー応答が不正です: {response}")
            if not int(match[1]):
                return errors
            errors.append(response)
        raise ProtocolError("実機のエラーが連続しています: " + " / ".join(errors))

    def archive_errors(self, context):
        errors = self.read_errors()
        if errors:
            logging.getLogger(__name__).warning("%sの未読エラー（今回の操作結果とは別）: %s", context, " / ".join(errors))
        return errors

    def check_error(self, context=""):
        errors = self.read_errors()
        if errors:
            hint = ("実機の測定状態を確認してください。" if context in (":START", ":STOP")
                    else "一部の設定は反映済みの可能性があります。設定を再読込してください。")
            raise ProtocolError(f"{context}: 実機エラー {' / '.join(errors)}。{hint}")

    def read_settings(self, channel=1):
        channel_number(channel)
        data = {"identity": self.identify(), "running": bool(int(self.number(":STATUS:CONDITION?")) & 1),
                "channel": channel}
        queries = {"tdiv": ":TIMEBASE:TDIV?", "sample_rate": ":TIMEBASE:SRATE?", "record_length": ":ACQUIRE:RLENGTH?",
                   "acquire_mode": ":ACQUIRE:MODE?", "high_resolution": ":ACQUIRE:RESOLUTION?", "trigger_mode": ":TRIGGER:MODE?",
                   "trigger_type": ":TRIGGER:TYPE?", "delay": ":TRIGGER:DELAY?"}
        queries.update({key: f":CHANNEL{channel}:{command}?" for key, command in {
            "display": "DISPLAY", "probe": "PROBE", "vdiv": "VDIV", "offset": "OFFSET",
            "position": "POSITION", "coupling": "COUPLING", "bandwidth": "BWIDTH", "invert": "INVERT"}.items()})
        for key, query in queries.items():
            data[key] = self.text(query)
        # LINE has no level/slope query; enhanced trigger settings remain untouched.
        data["source"] = self.text(":TRIGGER:SIMPLE:SOURCE?")
        if data["source"].upper() != "LINE":
            data["slope"] = self.text(":TRIGGER:SIMPLE:SLOPE?")
            data["level"] = self.text(":TRIGGER:SIMPLE:LEVEL?")
        return data

    def toggle_run(self, channel=1):
        channel_number(channel)
        running = bool(int(self.number(":STATUS:CONDITION?")) & 1)
        self.control("STOP" if running else "RUN")
        return self.read_settings(channel)

    def set_running(self, running, channel=1):
        """Honor the requested state even if acquisition completed while queued."""
        channel_number(channel)
        if type(running) is not bool:
            raise ValueError("RUN/STOPは真偽値で指定してください。")
        actual = bool(int(self.number(":STATUS:CONDITION?")) & 1)
        if actual != running:
            self.control("RUN" if running else "STOP")
            result = self.read_settings(channel)
            if self.control_warnings:
                result["warnings"] = self.control_warnings
            return result
        return self.read_settings(channel)

    def apply_settings(self, group, values, fields=None):
        channel_number(values.get("channel", 1))
        commands = settings_commands(group, values, fields)
        self.check_error("設定変更前の未読エラー")
        changes_record = any(command.startswith(':ACQUIRE:RLENGTH ') for command in commands)
        was_stopped = changes_record and not bool(int(self.number(':STATUS:CONDITION?')) & 1)
        for command in commands:
            self.write_checked(command)
        # F1.08 can start acquisition when record length changes in high
        # resolution mode. A setting edit must preserve a user's STOP state.
        if was_stopped and int(self.number(':STATUS:CONDITION?')) & 1:
            self.write_checked(':STOP')
        return self.read_settings(values.get("channel", 1))

    def capture_live(self, allow_pause=True, capture_stopped=True):
        """Prepare while running, pause only for binary transfer, then resume."""
        running = bool(int(self.number(":STATUS:CONDITION?")) & 1)
        if not running and not capture_stopped:
            return {"waiting": True, "running": False, "traces": [], "reason": "stopped"}
        if running:
            mode = self.text(":TRIGGER:MODE?").upper()
            if not allow_pause or mode.startswith(("SING", "NSIN")):
                return {"waiting": True, "running": True, "traces": [],
                        "reason": "single" if mode.startswith(("SING", "NSIN")) else "running"}
        traces = self._capture((1, 2, 3, 4), pause_running=running)
        return {"waiting": False, "running": running, "traces": traces,
                "pause_seconds": self.last_pause_seconds, "warnings": self.capture_warnings}

    def capture(self, channels=(1, 2, 3, 4)):
        if int(self.number(":STATUS:CONDITION?")) & 1:
            raise ProtocolError("波形取得中です。STOPを押してから読み出してください。")
        return self._capture(channels)

    def _capture(self, channels, pause_running=False):
        self.last_pause_seconds = 0.
        if any(channel not in (1, 2, 3, 4) for channel in channels):
            raise ValueError("CHは1〜4を指定してください。")
        self.capture_warnings = self.archive_errors("波形取得前")
        identity = self.identify()
        saved = {key: self.text(f":WAVEFORM:{key}?") for key in
                 ("TRACE", "RECORD", "START", "END", "DLENGTH", "FORMAT", "BYTEORDER")}
        try:
            time_div = self.number(":TIMEBASE:TDIV?")
            timebase_sample_rate = self.number(":TIMEBASE:SRATE?")
            self.write(":WAVEFORM:RECORD 0")
            self.write(":WAVEFORM:FORMAT WORD")
            self.write(":WAVEFORM:BYTEORDER MSBFIRST")
            self.write(":WAVEFORM:DLENGTH AUTO")
            plans = []
            for channel in channels:
                if not self.number(f":CHANNEL{channel}:DISPLAY?"):
                    continue
                if self.number(f":CHANNEL{channel}:LSCALE:MODE?"):
                    raise ProtocolError(f"CH{channel}: リニアスケールONの直接取得は未対応です。WVF/HDRを使用してください。")
                self.write(f":WAVEFORM:TRACE {channel}")
                length = int(self.number(":WAVEFORM:LENGTH?"))
                rate = self.number(":WAVEFORM:SRATE?")
                trigger = self.number(":WAVEFORM:TRIGGER?")
                scale = self.number(":WAVEFORM:RANGE?")
                offset = self.number(":WAVEFORM:OFFSET?")
                if length < 2 or length > 32_064_000 or not np.isfinite(rate) or rate <= 0:
                    raise ProtocolError("サンプル数またはサンプルレートが不正です。")
                vdiv = self.number(f":CHANNEL{channel}:VDIV?")
                plans.append((channel, length, rate, trigger, scale, offset, vdiv))
            if not plans:
                raise ProtocolError("指定CHはすべて表示OFFです。DL1640側でCHをONにしてください。")
            self.write(":WAVEFORM:START 0")
            selected_channel, selected_length = plans[-1][:2]
            self.write(f":WAVEFORM:END {selected_length-1}")
            paused = False
            replies = []
            try:
                if pause_running:
                    paused = True
                    pause_started = time.monotonic()
                    self.write(":STOP")
                    deadline = time.monotonic()+2
                    while int(self.number(":STATUS:CONDITION?")) & 1:
                        if time.monotonic() > deadline:
                            raise ProtocolError("実機の一時停止を確認できませんでした。")
                        time.sleep(.02)
                for channel, length, *_ in plans:
                    if channel != selected_channel:
                        self.write(f":WAVEFORM:TRACE {channel}")
                        selected_channel = channel
                    if length != selected_length:
                        self.write(f":WAVEFORM:END {length-1}")
                        selected_length = length
                    replies.append(self.query(":WAVEFORM:SEND?"))
            finally:
                if paused:
                    try:
                        self.write(":START")
                        self.last_pause_seconds = time.monotonic() - pause_started
                    except Exception as exc:
                        raise ProtocolError("ライブ取得後にRUNへ戻せませんでした。実機の測定状態を確認してください。") from exc
            # Resume before decoding, allocating arrays and restoring transfer settings.
            traces = []
            for (channel, length, rate, trigger, scale, offset, vdiv), reply in zip(plans, replies):
                block = decode_block(reply)
                if len(block) != length * 2:
                    raise ProtocolError(f"CH{channel}: 波形のバイト数が一致しません。")
                raw = np.frombuffer(block, dtype=">i2")
                y = raw.astype(float) * scale / 3072 + offset
                y[raw == 32767] = np.nan
                traces.append(Trace(f"CH{channel}", (np.arange(length) - trigger) / rate,
                    y, "V", COLORS[channel-1], metadata={"source": self.host, "instrument": identity,
                        "sample_rate": rate, "timebase_sample_rate": timebase_sample_rate,
                        "record": 0, "time_div": time_div,
                        "vertical_div": vdiv, "vertical_offset": offset, "vertical_range": scale}))
        finally:
            # Restore transfer settings, including if a channel read fails.
            for key, value in saved.items():
                self.write(f":WAVEFORM:{key} {value}")
        self.check_error("波形取得・転送設定の復元")
        return traces


def decode_block(message):
    start = message.find(b"#")
    if start < 0 or start + 2 > len(message):
        raise ProtocolError("波形のIEEEバイナリブロックがありません。")
    digit = message[start+1:start+2]
    if digit not in b"123456789":
        raise ProtocolError("不正なバイナリブロックヘッダです。")
    digits = int(digit)
    end_header = start + 2 + digits
    try:
        count = int(message[start+2:end_header])
    except ValueError as exc:
        raise ProtocolError("バイナリブロック長が不正です。") from exc
    if count < 0 or end_header + count > len(message):
        raise ProtocolError("波形データが途中で切れています。")
    return message[end_header:end_header+count]
