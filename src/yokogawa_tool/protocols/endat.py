"""Passive EnDat 2.1/2.2 position decoding. See docs/endat.md for scope and sources.

No encoder commands are transmitted. Clock/data are already captured samples.
"""
import numpy as np
from time import monotonic
from .models import Annotation
from .logic import logic_data

# Six wire bits, MSB first. EnDat 2.2 extensions are not all complementary codes.
COMMANDS = {
    0b000111: ('2.1', 'Send position', 'position'),
    0b001110: ('2.1', 'Select memory area', 'parameter'),
    0b011100: ('2.1', 'Receive parameter', 'parameter'),
    0b100011: ('2.1', 'Send parameter', 'parameter'),
    0b101010: ('2.1', 'Reset', 'parameter'),
    0b010101: ('2.1', 'Send test values', 'test'),
    0b110001: ('2.1', 'Receive test command', 'parameter'),
    0b111000: ('2.2', 'Send position + additional data', 'position'),
    0b001001: ('2.2', 'Position + select memory/additional data', 'position'),
    0b011011: ('2.2', 'Position + receive parameter', 'position'),
    0b100100: ('2.2', 'Position + send parameter', 'position'),
    0b110110: ('2.2', 'Position + receive test command', 'position'),
    0b101101: ('2.2', 'Position + error reset', 'position'),
    0b010010: ('2.2', 'Communication command', 'parameter'),
}


def crc5(bits):
    """EnDat CRC: x^5+x^3+x+1, initial all ones, inverted MSB-first result."""
    crc = 0x1f
    for bit in bits:
        feedback = ((crc >> 4) ^ int(bit)) & 1
        crc = ((crc << 1) & 0x1f) ^ (0x0b if feedback else 0)
    return crc ^ 0x1f


def unsigned(bits, lsb=False):
    return sum(int(bit) << i for i, bit in enumerate(bits if lsb else bits[::-1]))


def decode_endat(channels, thresholds, options=None):
    started = monotonic()
    if set(channels) != {'clk', 'data'}:
        raise ValueError('EnDatにはCLOCKと双方向DATAの2信号が必要です。')
    options = dict(options or {})
    defaults = dict(position_bits=25, initial_clocks=2, turnaround_clocks=2,
                    idle_gap_us=10, response_delay_ns=0, additional=0,
                    invert_clk=0, invert_data=0)
    if set(options) - set(defaults):
        raise ValueError('EnDatの復号オプションが不正です。')
    config = {**defaults, **options}
    limits = dict(position_bits=(1, 64), initial_clocks=(0, 8), turnaround_clocks=(0, 8),
                  idle_gap_us=(.01, 1e6), response_delay_ns=(-1e6, 1e6),
                  additional=(0, 2), invert_clk=(0, 1), invert_data=(0, 1))
    for key, (low, high) in limits.items():
        try:
            value = float(config[key])
        except (ValueError, TypeError) as exc:
            raise ValueError(f'{key}の値が不正です。') from exc
        if not np.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{key}は{low:g}〜{high:g}で指定してください。')
        if key not in ('idle_gap_us', 'response_delay_ns') and not value.is_integer():
            raise ValueError(f'{key}は整数で指定してください。')
        config[key] = value if key in ('idle_gap_us', 'response_delay_ns') else int(value)
    packed, dt, origin = logic_data({'clk': channels['clk'], 'data': channels['data']}, thresholds)
    clk = ((packed & 1) != 0) ^ bool(config['invert_clk'])
    data = ((packed & 2) != 0) ^ bool(config['invert_data'])
    falls = np.flatnonzero(clk[:-1] & ~clk[1:]) + 1
    rises = np.flatnonzero(~clk[:-1] & clk[1:]) + 1
    if not len(falls) or not len(rises):
        raise ValueError('EnDatのクロックが検出できません。CH・しきい値・極性を確認してください。')
    if len(falls) > 1 and np.median(np.diff(falls)) < 4:
        raise ValueError('EnDatにはクロック1周期あたり4サンプル以上が必要です。T/div・記録長を見直してください。')
    gap = config['idle_gap_us'] * 1e-6 / dt
    # A frame must start after a visible high idle interval. Do not guess a
    # command when the recording begins in the middle of a transaction.
    prior = np.searchsorted(rises, falls) - 1
    high_start = np.where(prior >= 0, rises[np.maximum(prior, 0)], 0)
    # clk[0] only governs the initial high region, not subsequent valid frames.
    starts = np.flatnonzero((falls - high_start >= gap * (1-1e-9)) & ((prior >= 0) | clk[0]))
    events = []

    def emit(a, b, kind, text):
        if len(events) >= 100000:
            raise ValueError('EnDatの復号結果が100,000件を超えました。短い記録で再試行してください。')
        events.append(Annotation(origin + float(a)*dt, origin + float(b)*dt, kind, text))

    for frame, first in enumerate(starts):
        if monotonic() - started > 30:
            raise ValueError('EnDatの復号が30秒以内に完了しませんでした。短い記録で再試行してください。')
        stop = int(starts[frame+1]) if frame+1 < len(starts) else len(falls)
        frame_falls = falls[first:stop]
        next_rise = np.searchsorted(rises, frame_falls, side='right')
        valid = next_rise < len(rises)
        frame_falls, next_rise = frame_falls[valid], next_rise[valid]
        if not len(frame_falls):
            continue
        frame_rises = rises[next_rise]
        # Sample in the centre of each stable half cycle, not on an edge.
        low_samples = (frame_falls + frame_rises) // 2
        next_falls = np.r_[frame_falls[1:], min(len(clk)-1, frame_rises[-1] + (frame_rises[-1]-frame_falls[-1]))]
        high_samples = (frame_rises + next_falls) // 2
        prefix = config['initial_clocks']
        if len(frame_falls) < prefix+6:
            emit(frame_falls[0], frame_rises[-1], 'warning', 'Truncated command')
            continue
        bits = data[high_samples[prefix:prefix+6]]
        command = unsigned(bits)
        a, b = frame_falls[prefix], frame_rises[prefix+5]
        if command not in COMMANDS:
            emit(a, b, 'warning', f'Unknown/invalid mode {command:06b}')
            continue
        version, title, kind = COMMANDS[command]
        emit(a, b, 'command', f'EnDat {version}: {title} ({command:06b})')
        tx_extra = 24 if command in (0b001110, 0b011100, 0b100011, 0b101010, 0b110001, 0b010010) else 0
        after = prefix + 6 + tx_extra + config['turnaround_clocks']
        shift = round(config['response_delay_ns'] * 1e-9 / dt)
        sample_indices = low_samples + shift
        valid_samples = (sample_indices >= 0) & (sample_indices < len(data))
        # Never move a response sample across the following frame boundary.
        boundary = falls[stop] if stop < len(falls) else len(data)
        valid_samples &= sample_indices < boundary
        valid_samples &= sample_indices >= frame_falls[0]
        sample_bits = np.zeros(len(low_samples), dtype=bool)
        sample_bits[valid_samples] = data[sample_indices[valid_samples]]
        candidates = np.flatnonzero(sample_bits[after:] & valid_samples[after:]) + after
        if not len(candidates):
            emit(b, frame_rises[-1], 'warning', 'Response START not found')
            continue
        start = int(candidates[0])
        nflags = (2 if version == '2.2' else 1) if kind in ('position', 'test') else 0
        ndata = 40 if kind == 'test' else config['position_bits'] if kind == 'position' else 24
        end = start + 1 + nflags + ndata + 5
        if end > len(sample_bits) or not np.all(valid_samples[start:end]):
            emit(frame_falls[start], frame_rises[-1], 'warning', 'Truncated response')
            continue
        payload = sample_bits[start+1:end-5]
        flags, values = payload[:nflags], payload[nflags:]
        for index, flag in enumerate(flags):
            emit(frame_falls[start+1+index], frame_rises[start+1+index], f'F{index+1}', str(int(flag)))
        offset = start + 1 + nflags
        if kind in ('position', 'test'):
            value = unsigned(values, lsb=True)
            emit(frame_falls[offset], frame_rises[end-6], kind, f'{value} (0x{value:X}, {ndata} bit)')
        else:
            emit(frame_falls[offset], frame_rises[end-6], 'parameter',
                 f'Address 0x{unsigned(values[:8]):02X}, data 0x{unsigned(values[8:]):04X}')
        received, expected = unsigned(sample_bits[end-5:end]), crc5(payload)
        emit(frame_falls[end-5], frame_rises[end-1], 'crc' if received == expected else 'warning',
             f'CRC {"OK" if received == expected else "ERROR"}: received 0x{received:02X}, expected 0x{expected:02X}')
        # Additional information carries 24 bits + CRC, separated by one clock.
        if version == '2.2' and kind == 'position':
            for index in range(config['additional']):
                pos = end + 1
                end = pos + 29
                if end > len(sample_bits) or not np.all(valid_samples[pos:end]):
                    emit(frame_rises[min(pos-1, len(frame_rises)-1)], frame_rises[-1], 'warning', 'Truncated additional data')
                    break
                value_bits = sample_bits[pos:pos+24]
                received, expected = unsigned(sample_bits[pos+24:end]), crc5(value_bits)
                emit(frame_falls[pos], frame_rises[pos+23], 'additional', f'Block {index+1}: 0x{unsigned(value_bits):06X}')
                emit(frame_falls[pos+24], frame_rises[end-1], 'crc' if received == expected else 'warning',
                     f'Additional CRC {"OK" if received == expected else "ERROR"}: received 0x{received:02X}, expected 0x{expected:02X}')
            if command != 0b111000:
                emit(frame_falls[0], frame_rises[-1], 'warning', 'Supplement command payload is not interpreted')
    if not events:
        raise ValueError('完全なEnDatフレームが見つかりません。先頭のアイドル期間を含め、Idle gapと開始クロック数を確認してください。')
    return sorted(events, key=lambda event: (event.start, event.end, event.kind))
