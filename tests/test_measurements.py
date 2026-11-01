import numpy as np
import pytest
from yokogawa_tool.core.measurements import METRICS, measure, extract_edges


ALL = [m.key for m in METRICS]


def test_trapezoid_frequency_duty_and_10_90_times():
    x = np.arange(0, 3, .0005)
    phase = x % 1
    y = np.interp(phase, [0, .2, .3, .6, .7, 1], [0, 0, 4, 4, 0, 0])
    original = y.copy()
    result = measure(x, y, ALL)
    for key, expected in {'frequency': 1, 'period': 1, 'positive_duty': 40,
        'negative_duty': 60, 'positive_width': .4, 'negative_width': .6,
        'rise': .08, 'fall': .08, 'low': 0, 'high': 4, 'amplitude': 4,
        'rising_count': 3, 'falling_count': 3}.items():
        assert result[key] == pytest.approx(expected, abs=1e-10), key
    np.testing.assert_array_equal(y, original)


def test_sine_voltage_statistics_and_frequency():
    x = np.arange(10000) / 10000
    y = 2 + np.sin(2 * np.pi * 10 * x)
    result = measure(x, y, ALL)
    for key, expected in {'min': 1, 'max': 3, 'pp': 2, 'mean': 2, 'median': 2,
        'rms': np.sqrt(4.5), 'std': np.sqrt(.5), 'ac_rms': np.sqrt(.5),
        'frequency': 10, 'positive_duty': 50}.items():
        assert result[key] == pytest.approx(expected, rel=1e-9), key


def test_nan_gap_does_not_create_period_or_edge():
    x = np.array([0, 1, 2, 3, 10, 100, 101, 102, 103.])
    y = np.array([0, 4, 0, 0, np.nan, 0, 4, 0, 0])
    result = measure(x, y, ALL)
    assert result['rising_count'] == result['falling_count'] == 2
    assert np.isnan(result['frequency']) and np.isnan(result['positive_duty'])
    assert result['positive_width'] == 1
    assert np.isnan(result['negative_width'])


def test_midlevel_noise_is_not_counted_as_extra_edges():
    x = np.arange(10.)
    y = np.array([0, 0, 1.9, 2.1, 1.9, 2.2, 4, 4, 4, 4])
    edges = extract_edges(x, y, 0, 4)
    assert len(edges.times) == 1 and edges.rising[0]
    assert edges.times[0] == 2.5


def test_constant_and_empty_ranges_have_no_timing_measurements():
    for y in (np.ones(20), np.full(20, np.nan), np.array([])):
        result = measure(np.arange(len(y)), y, ALL)
        assert np.isnan(result['frequency']) and np.isnan(result['rise'])
    assert measure(np.arange(3.), np.ones(3), []) == {}
    with pytest.raises(ValueError):
        measure(np.arange(3.), np.ones(3), ['unknown'])
    y = np.tile([1., np.nextafter(1., 2.)], 10)
    assert np.isnan(measure(np.arange(len(y)), y, ['frequency'])['frequency'])


def test_narrow_pulse_and_nonuniform_time_grid():
    x = np.arange(10000.) * .0001
    y = np.where(np.arange(len(x)) % 1000 < 10, 3.3, 0)
    result = measure(x, y, ['frequency', 'positive_duty'])
    assert result['frequency'] == pytest.approx(10)
    assert result['positive_duty'] == pytest.approx(1)
    x = np.array([0., .2, .4, .6, 1, 1.2, 1.4, 1.6])
    y = np.array([0., 4, 4, 0, 0, 4, 4, 0])
    assert measure(x, y, ['period'])['period'] == pytest.approx(1)
