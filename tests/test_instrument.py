import struct
import numpy as np
import pytest
from yokogawa_tool.acquisition.instrument import DL1640, ProtocolError, decode_block


class FragmentedSocket:
    """TCP may split a header or combine complete frames arbitrarily."""
    def __init__(self, data):
        self.data = bytearray(data)
        self.sent = bytearray()

    def recv(self, count):
        result = bytes(self.data[:min(count, 2)])
        del self.data[:len(result)]
        return result

    def settimeout(self, timeout):
        pass

    def sendall(self, data):
        self.sent.extend(data)

    def close(self):
        pass


def frame(data, final=True):
    return struct.pack(">I", len(data) | (0x80000000 if final else 0)) + data


def test_fragmented_frames_and_multiframe_message():
    scope = DL1640("test")
    scope.socket = FragmentedSocket(frame(b"abc", False) + frame(b"def"))
    assert scope._receive() == b"abcdef"


def test_handshake_empty_ack_frames(monkeypatch):
    sock = FragmentedSocket(frame(b"username:") + frame(b"") + frame(b"password:") +
                            frame(b"") + frame(b"Ctl server is ready.") + frame(b"YOKOGAWA,701610,0,F1.08\n"))
    monkeypatch.setattr("socket.create_connection", lambda *args: sock)
    with DL1640("test") as scope:
        assert "701610" in scope.identify()
    assert bytes(sock.sent) == frame(b"anonymous") + frame(b"") + frame(b"*IDN?")


def test_closed_socket_and_oversized_header():
    for data in [b"", struct.pack(">I", 0xffffffff)]:
        scope = DL1640("test")
        scope.socket = FragmentedSocket(data)
        with pytest.raises(ProtocolError):
            scope._receive()


def test_block_can_contain_newline_and_nul():
    assert decode_block(b":WAVEFORM:SEND #14\x00\n\x80\xff\n") == b"\x00\n\x80\xff"
    for bad in (b"abc", b"#0abc", b"#14ab", b"#2xxabcd"):
        with pytest.raises(ProtocolError):
            decode_block(bad)


class FakeScope(DL1640):
    def __init__(self, running=False, broken=False):
        super().__init__("test")
        self.commands = []
        self.running = running
        self.broken = broken

    def write(self, command):
        self.commands.append(command)

    def text(self, command):
        if command == ":STATUS:ERROR?":
            return '0,"No error"'
        return {"TRACE": "1", "RECORD": "0", "START": "0", "END": "2", "DLENGTH": "AUTO",
                "FORMAT": "ASCII", "BYTEORDER": "LSBFIRST"}.get(command.split(":")[-1].rstrip("?"), "YOKOGAWA,701610,0,F1.08")

    def number(self, command):
        if command == ":TIMEBASE:TDIV?":
            return .001
        if command == ":TIMEBASE:SRATE?":
            return 10
        if command.endswith(":VDIV?"):
            return .5
        if "CONDITION" in command:
            return int(self.running)
        if "DISPLAY" in command:
            return 1
        if "LSCALE" in command:
            return 0
        return {"LENGTH": 3, "SRATE": 10, "TRIGGER": 1, "RANGE": 3, "OFFSET": 1}[command.split(":")[-1].rstrip("?")]

    def query(self, command):
        return b"#16" + (b"bad" if self.broken else struct.pack(">3h", 0, 3072, 32767))


def test_capture_scaling_and_restoration():
    scope = FakeScope()
    trace, = scope.capture([1])
    np.testing.assert_allclose(trace.x, [-.1, 0, .1])
    np.testing.assert_allclose(trace.y, [1, 4, np.nan])
    assert scope.commands[-2:] == [":WAVEFORM:FORMAT ASCII", ":WAVEFORM:BYTEORDER LSBFIRST"]


def test_capture_requires_stop_and_restores_on_error():
    scope = FakeScope(running=True)
    with pytest.raises(ProtocolError, match="STOP"):
        scope.capture([1])
    assert not scope.commands
    scope = FakeScope(broken=True)
    with pytest.raises(ProtocolError):
        scope.capture([1])
    assert scope.commands[-2:] == [":WAVEFORM:FORMAT ASCII", ":WAVEFORM:BYTEORDER LSBFIRST"]
