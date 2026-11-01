"""Synthetic wire captures and fixed CRC vectors from TI's independent C reference."""
import numpy as np
import pytest
from yokogawa_tool.core.waveform import Trace
from yokogawa_tool.protocols import decode
from yokogawa_tool.protocols.endat import crc5


def bits(value, count, lsb=False):
    return [(value >> i) & 1 for i in (range(count) if lsb else range(count-1, -1, -1))]


@pytest.mark.parametrize('payload,expected', [
    ([0] + bits(0x123456, 25, True), 11),
    ([1, 0] + bits(0x512345678, 35, True), 27),
    ([0, 1] + bits(0xfedcba9876543210, 64, True), 11),
    (bits(0xabcdef, 24), 16), (bits(0x123456, 24), 1)])
def test_crc_matches_independent_ti_reference(payload, expected):
    assert crc5(payload) == expected


def capture(command, response, *, tx=None, initial=2, delay=0, invert=False):
    """CLOCK high idle; commands change on fall, encoder changes on rise."""
    clk, data = [1]*600, [0]*600  # 30 µs idle, Fs=20 MHz
    mode = bits(command, 6)
    transmitted = [1]*initial + mode + list(tx or []) + [0, 0]
    # Encode command bits across both half cycles. Encoder's START appears on
    # the preceding rising edge, so its first stable low half is cycle N+1.
    for index, bit in enumerate(transmitted):
        clk.extend([0]*10 + [1]*10)
        data.extend([bit]*10 + ([1]*10 if index == len(transmitted)-1 else [bit]*10))
    for index, bit in enumerate(response):
        clk.extend([0]*10 + [1]*10)
        next_bit = response[index+1] if index+1 < len(response) else 1
        data.extend([bit]*10 + [next_bit]*10)
    clk.extend([1]*600); data.extend([0]*600)
    if delay:
        data = [0]*delay + data[:-delay]
    if invert:
        clk = [1-v for v in clk]; data = [1-v for v in data]
    x = -.02 + np.arange(len(clk))/20e6
    return {key: Trace(key, x, np.array(y)*3.3) for key, y in [('clk', clk), ('data', data)]}


def run(channels, options=None):
    return decode('endat', channels, dict(clk=1.65, data=1.65), options, executable='missing-sigrok')


def test_endat21_position_timing_and_original_arrays():
    channels = capture(0b000111, [1, 0] + bits(0x123456, 25, True) + bits(11, 5))
    original = channels['data'].y.copy()
    events = run(channels)
    assert any('EnDat 2.1' in e.text for e in events)
    position, = [e for e in events if e.kind == 'position']
    assert '1193046' in position.text
    assert position.start == pytest.approx(-.02 + 42e-6)  # 30us idle + 10 cycles + START + F1
    assert any('CRC OK' in e.text for e in events)
    assert not [e for e in events if e.kind == 'warning']
    np.testing.assert_array_equal(channels['data'].y, original)


def test_endat22_flags_35bit_position_and_additional_crc():
    response = ([1, 1, 0] + bits(0x512345678, 35, True) + bits(27, 5)
                + [0] + bits(0xabcdef, 24) + bits(16, 5))
    events = run(capture(0b111000, response), dict(position_bits=35, additional=1))
    assert any('0x512345678' in e.text for e in events)
    assert [(e.kind, e.text) for e in events if e.kind in ('F1', 'F2')] == [('F1', '1'), ('F2', '0')]
    assert any('0xABCDEF' in e.text for e in events)
    assert len([e for e in events if e.kind == 'crc']) == 2
    assert not [e for e in events if e.kind == 'warning']


def test_64bit_position_and_two_additional_blocks():
    response = ([1, 0, 1] + bits(0xfedcba9876543210, 64, True) + bits(11, 5)
                + [0] + bits(0xabcdef, 24) + bits(16, 5)
                + [0] + bits(0x123456, 24) + bits(1, 5))
    events = run(capture(0b111000, response), dict(position_bits=64, additional=2))
    assert len([e for e in events if e.kind == 'crc']) == 3
    assert any('0xFEDCBA9876543210' in e.text for e in events)
    assert len([e for e in events if e.kind == 'additional']) == 2
    assert not [e for e in events if e.kind == 'warning']


def test_parameter_response_and_bad_crc_and_incomplete_frame():
    events = run(capture(0b100011, [1]+bits(0x123456, 24)+bits(1, 5), tx=[0]*24))
    assert any('Address 0x12, data 0x3456' == e.text for e in events)
    assert any(e.kind == 'crc' for e in events)
    events = run(capture(0b000111, [1, 0]+bits(0x123456, 25, True)+bits(10, 5)))
    assert any('CRC ERROR' in e.text for e in events)
    events = run(capture(0b000111, [1, 0, 1]))
    assert any('Truncated response' in e.text for e in events)
    events = run(capture(0b000000, [0]*20))
    assert any('Unknown/invalid' in e.text for e in events)


def test_multiple_frames_delay_polarity_and_no_idle_rejection():
    one = capture(0b000111, [1, 0]+bits(0x123456, 25, True)+bits(11, 5))
    both = {key: Trace(key, -.02+np.arange(2*len(t.x))/20e6, np.tile(t.y, 2)) for key, t in one.items()}
    assert len([e for e in run(both) if e.kind == 'position']) == 2
    delayed = capture(0b000111, [1, 0]+bits(0x123456, 25, True)+bits(11, 5), delay=7)
    assert any(e.kind == 'crc' for e in run(delayed, dict(response_delay_ns=350)))
    inverted = capture(0b000111, [1, 0]+bits(0x123456, 25, True)+bits(11, 5), invert=True)
    assert any(e.kind == 'crc' for e in run(inverted, dict(invert_clk=1, invert_data=1)))
    clipped = {key: Trace(key, t.x[610:], t.y[610:]) for key, t in one.items()}
    with pytest.raises(ValueError, match='フレーム'):
        run(clipped)


@pytest.mark.parametrize('options', [dict(position_bits=0), dict(position_bits=25.5),
    dict(additional=3), dict(idle_gap_us=float('nan')), dict(response_delay_ns=float('inf')), dict(unknown=1)])
def test_invalid_options_rejected(options):
    channels = capture(0b000111, [1, 0]+bits(0x123456, 25, True)+bits(11, 5))
    with pytest.raises(ValueError):
        run(channels, options)


def test_endat_dialog_uses_native_engine(tmp_path):
    from PySide6 import QtCore, QtWidgets as W, QtTest
    from yokogawa_tool.gui.protocol_panel import ProtocolDialog
    app = W.QApplication.instance() or W.QApplication([])
    channels = capture(0b000111, [1, 0]+bits(0x123456, 25, True)+bits(11, 5))
    settings = QtCore.QSettings(str(tmp_path/'endat.ini'), QtCore.QSettings.IniFormat)
    dialog = ProtocolDialog(list(channels.values()), settings)
    dialog.protocol.setCurrentIndex(dialog.protocol.findData('endat'))
    assert not dialog.tool.isEnabled() and not dialog.browse.isEnabled()
    assert dialog.options['position_bits'].value() == 25
    assert set(dialog.channels) == {'clk', 'data'}
    dialog.tool.setText('nonexistent-sigrok')
    dialog.start_decode()
    for _ in range(100):
        QtTest.QTest.qWait(10)
        if dialog.worker is None:
            break
    assert dialog.worker is None
    assert any('CRC OK' in event.text for event in dialog.events)
    assert not dialog.tool.isEnabled() and not dialog.browse.isEnabled()
    dialog.close()
