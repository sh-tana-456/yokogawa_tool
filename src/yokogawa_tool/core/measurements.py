"""Selectable measurements over original samples; no display downsampling."""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class Metric:
    key: str
    title: str
    unit: str = 'signal'


METRICS = [Metric('min', 'Min'), Metric('max', 'Max'), Metric('pp', 'P-P'),
    Metric('mean', 'Mean'), Metric('rms', 'RMS'), Metric('std', '標準偏差'),
    Metric('ac_rms', 'AC RMS'), Metric('median', '中央値'), Metric('low', 'Low'),
    Metric('high', 'High'), Metric('amplitude', '振幅 High−Low'),
    Metric('frequency', '周波数', 'Hz'), Metric('period', '周期', 's'),
    Metric('positive_duty', '正デューティ', '%'), Metric('negative_duty', '負デューティ', '%'),
    Metric('positive_width', '正パルス幅', 's'), Metric('negative_width', '負パルス幅', 's'),
    Metric('rise', '立上り 10–90%', 's'), Metric('fall', '立下り 90–10%', 's'),
    Metric('rising_count', '立上り回数', ''), Metric('falling_count', '立下り回数', '')]
DEFAULT_METRICS = ['min', 'max', 'pp', 'mean', 'rms', 'frequency', 'period', 'positive_duty']
EDGE_METRICS = {m.key for m in METRICS[11:]}


@dataclass
class Edges:
    times: np.ndarray
    rising: np.ndarray
    durations: np.ndarray
    segments: np.ndarray


def signal_levels(y):
    """Estimate two plateaus by median clustering, limiting estimation work."""
    if not len(y):
        return np.nan, np.nan
    sample = y[::max(1, len(y) // 65536)]
    low, high = np.quantile(sample, [.05, .95])
    if high == low:
        low, high = np.min(y), np.max(y)
    for _ in range(6):
        lower = sample <= (low + high) / 2
        if lower.all() or not lower.any():
            break
        low, high = np.median(sample[lower]), np.median(sample[~lower])
    return float(low), float(high)


def extract_edges(x, y, low, high):
    """10/90% hysteresis confirms edges; interpolate 50% times, retain gaps.

    This standalone operation can also feed future digital protocol decoders.
    """
    empty = Edges(np.array([]), np.array([], dtype=bool), np.array([]), np.array([], dtype=int))
    if len(y) < 2 or not np.isfinite(low + high) or high <= low:
        return empty
    bottom, middle, top = low + .1 * (high - low), (low + high) / 2, low + .9 * (high - low)
    if not low < bottom < middle < top < high:
        return empty  # The amplitude is too small to represent distinct thresholds.
    finite = np.isfinite(y)
    marked = np.flatnonzero(~finite | (y <= bottom) | (y >= top))
    states = np.where(finite[marked], (y[marked] >= top).astype(int), -1)
    changes = np.flatnonzero((states[1:] != states[:-1]) & (states[1:] >= 0) & (states[:-1] >= 0)) + 1
    if not len(changes):
        return empty
    left, right = marked[changes - 1], marked[changes]
    rising = states[changes] == 1
    times = np.empty(len(changes))
    def interpolate(index, level):
        return x[index] + (level - y[index]) / (y[index + 1] - y[index]) * (x[index + 1] - x[index])
    for direction in (False, True):
        crossings = np.flatnonzero(finite[:-1] & finite[1:] &
            ((y[:-1] < middle) & (y[1:] >= middle) if direction else (y[:-1] > middle) & (y[1:] <= middle)))
        chosen = rising == direction
        indices = crossings[np.searchsorted(crossings, left[chosen])]
        times[chosen] = interpolate(indices, middle)
    start_level = np.where(rising, bottom, top)
    end_level = np.where(rising, top, bottom)
    durations = interpolate(right - 1, end_level) - interpolate(left, start_level)
    return Edges(times, rising, durations, np.cumsum(~finite)[left])


def measure(x, y, selected):
    selected = set(selected)
    if selected - {m.key for m in METRICS}:
        raise ValueError('未対応の測定項目です。')
    result = {key: np.nan for key in selected}
    values = y[np.isfinite(y)]
    if not len(values):
        return result
    basic = {'min': np.min, 'max': np.max, 'pp': np.ptp, 'mean': np.mean,
             'median': np.median, 'std': np.std,
             'rms': lambda v: np.sqrt(np.mean(v * v)),
             'ac_rms': lambda v: np.sqrt(np.mean((v - np.mean(v)) ** 2))}
    for key in selected & basic.keys():
        result[key] = float(basic[key](values))
    if not selected & (EDGE_METRICS | {'low', 'high', 'amplitude'}):
        return result
    low, high = signal_levels(values)
    for key, value in (('low', low), ('high', high), ('amplitude', high - low)):
        if key in selected:
            result[key] = value
    if not selected & EDGE_METRICS:
        return result
    edges = extract_edges(x, y, low, high)
    times, rising, segments = edges.times, edges.rising, edges.segments
    computed = {'rising_count': int(rising.sum()), 'falling_count': int((~rising).sum())}
    def median(values):
        return float(np.median(values)) if len(values) else np.nan
    periods = []
    for direction, key in ((True, 'rise'), (False, 'fall')):
        chosen = rising == direction
        t, s = times[chosen], segments[chosen]
        periods.extend(np.diff(t)[np.diff(s) == 0])
        computed[key] = median(edges.durations[chosen])
    period = median(periods)
    computed.update(period=period, frequency=1 / period if period > 0 else np.nan)
    widths = np.diff(times)
    adjacent = np.diff(segments) == 0
    for direction, key in ((True, 'positive_width'), (False, 'negative_width')):
        computed[key] = median(widths[adjacent & (rising[:-1] == direction)])
    cycles = ((rising[:-2] == rising[2:]) & (rising[:-2] != rising[1:-1]) &
              (segments[:-2] == segments[2:]))
    total = times[2:] - times[:-2]
    fractions = np.where(rising[:-2], widths[:-1], widths[1:])[cycles] / total[cycles]
    computed['positive_duty'] = median(fractions) * 100
    computed['negative_duty'] = 100 - computed['positive_duty']
    result.update({key: computed[key] for key in selected & computed.keys()})
    return result
