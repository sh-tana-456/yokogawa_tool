import os
import sys
import shlex
from types import SimpleNamespace
from pathlib import Path
import numpy as np
import pytest
from yokogawa_tool.protocols import decode, logic_data, parse_trace_events
from yokogawa_tool.core.waveform import Trace


def traces(signals, rate=1000000):
    return {key: Trace(key, -.1 + np.arange(len(y))/rate, np.array(y, dtype=float)*3.3)
            for key, y in signals.items()}


def test_logic_packing_alignment_gaps_and_annotation_time():
    channels = traces({'scl': [0, 1, 0], 'sda': [1, 1, 0]})
    data, dt, origin = logic_data(channels, {'scl': 1.65, 'sda': 1.65})
    np.testing.assert_array_equal(data, [2, 3, 0])
    event, = parse_trace_events('{"traceEvents": [{"ph":"B","ts":10,"tid":"RX","name":"A5"},'
                               '{"ph":"E","ts":20,"tid":"RX"}]}', dt, origin)
    assert event.text == 'A5' and event.start == pytest.approx(origin+10e-6)
    channels['scl'].y[1] = np.nan
    with pytest.raises(ValueError, match='欠損'):
        logic_data(channels, {'scl': 1.65, 'sda': 1.65})


def test_invalid_config_is_rejected_before_running_tool():
    with pytest.raises(ValueError):
        decode('uart', traces({'rx': [1, 0, 1]}), {'rx': 1.65}, {'baudrate': '1:spi'}, executable='missing')
    with pytest.raises(ValueError, match='必要'):
        decode('spi', {}, {}, executable='missing')
    with pytest.raises(ValueError, match='見つかりません'):
        decode('uart', traces({'rx': [1, 0, 1]}), {'rx': 1.65}, executable='not-a-real-tool-xyz')
    with pytest.raises(ValueError, match='等間隔'):
        logic_data({'rx': Trace('rx', [0, 1, 3], [0, 1, 0])}, {'rx': .5})


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux frozen library environment')
@pytest.mark.parametrize('original', (None, '/original/system/lib'))
def test_frozen_decoder_child_uses_original_system_library_path(tmp_path, monkeypatch, original):
    from yokogawa_tool.protocols import sigrok
    output = tmp_path/'environment.txt'
    tool = tmp_path/'fake-sigrok'
    tool.write_text('#!/bin/sh\nprintf "%s" "$LD_LIBRARY_PATH" > '+shlex.quote(str(output))+
                    '\nprintf "%s" \'{"traceEvents": []}\'\n')
    tool.chmod(0o755)
    monkeypatch.setattr(sigrok, 'sys', SimpleNamespace(frozen=True, platform='linux'))
    monkeypatch.setenv('LD_LIBRARY_PATH', '/bundle/_internal')
    if original is None:
        monkeypatch.delenv('LD_LIBRARY_PATH_ORIG', raising=False)
    else:
        monkeypatch.setenv('LD_LIBRARY_PATH_ORIG', original)
    assert decode('uart', traces({'rx': [0, 1, 0]}), {'rx': 1.65}, executable=str(tool)) == []
    assert output.read_text() == (original or '')
    assert os.environ['LD_LIBRARY_PATH'] == '/bundle/_internal'


def uart_fixture():
    bits = [1]*3 + [0] + [(0xA5 >> i)&1 for i in range(8)] + [1]*3
    return traces({'rx': np.repeat(bits, 100)}, 10000), {'baudrate': 100}, 'rx-data', 'A5'


def spi_fixture():
    clk, data, cs = [0]*80, [0]*80, [1]*80
    for bit in [(0xA5 >> i)&1 for i in range(7, -1, -1)]:
        clk += [0]*20 + [1]*20; data += [bit]*40; cs += [0]*40
    clk += [0]*80; data += [0]*80; cs += [1]*80
    return traces({'clk': clk, 'mosi': data, 'cs': cs}), {}, 'mosi-data', 'A5'


def i2c_fixture():
    clk, data = [], []
    def hold(scl, sda, length=30):
        clk.extend([scl]*length); data.extend([sda]*length)
    hold(1, 1); hold(1, 0)
    for value, ack in ((0xA0, 0), (0x5A, 1)):
        for bit in [(value >> i)&1 for i in range(7, -1, -1)] + [ack]:
            hold(0, bit); hold(1, bit)
    hold(0, 0); hold(1, 0); hold(1, 1)
    return traces({'scl': clk, 'sda': data}), {}, 'data-write', '5A'


def can_fixture():
    def bits(value, n):
        return [(value >> i)&1 for i in range(n-1, -1, -1)]
    frame = [0] + bits(0x123, 11) + [0, 0, 0] + bits(1, 4) + bits(0xA5, 8)
    crc = 0
    for bit in frame:
        carry = (crc >> 14) ^ bit
        crc = (crc << 1) & 0x7FFF
        if carry: crc ^= 0x4599
    stuffed, previous, count = [], None, 0
    for bit in frame + bits(crc, 15):
        count = count+1 if bit == previous else 1
        stuffed.append(bit); previous = bit
        if count == 5:
            stuffed.append(1-bit); previous, count = 1-bit, 1
    signal = [1]*13 + stuffed + [1, 0, 1] + [1]*10
    return traces({'can_rx': np.repeat(signal, 20)}), {'nominal_bitrate': 50000}, 'data', 'A5'


@pytest.mark.parametrize('protocol,factory', [('uart', uart_fixture), ('spi', spi_fixture),
                                            ('i2c', i2c_fixture), ('can', can_fixture)])
def test_actual_sigrok_engine(protocol, factory):
    executable = os.environ.get('YOKOGAWA_TEST_SIGROK_CLI')
    if not executable:
        pytest.skip('Optional external decoder integration test')
    channels, options, kind, expected = factory()
    originals = [t.y.copy() for t in channels.values()]
    result = decode(protocol, channels, dict.fromkeys(channels, 1.65), options, executable)
    assert any(expected in e.text.upper() for e in result), result
    for trace, original in zip(channels.values(), originals):
        np.testing.assert_array_equal(trace.y, original)
