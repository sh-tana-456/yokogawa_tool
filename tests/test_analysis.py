import numpy as np
import pytest
from yokogawa_tool.core.waveform import Trace
from yokogawa_tool.core.analysis import expression_trace, transform, spectrum


def test_math_arithmetic_and_division_gaps():
    traces = [Trace("CH1", [0, 1, 2], [2, 4, 6]), Trace("CH2", [0, 1, 2], [1, 0, 3])]
    np.testing.assert_allclose(expression_trace("(CH1 - CH2) * 2", traces).y, [2, 8, 6])
    np.testing.assert_allclose(expression_trace("CH1 / CH2", traces).y, [2, np.nan, 2])


@pytest.mark.parametrize("expression", ["__import__('os').system('echo unsafe')", "CH1[0]", "CH1.__class__", "CH1 ** 1000", "open('file')", "[CH1]", "CH1 ** CH1"])
def test_math_rejects_executable_or_unsafe_expressions(expression):
    with pytest.raises(ValueError):
        expression_trace(expression, [Trace("CH1", [0, 1], [1, 2])])


def test_math_rejects_mismatched_grids():
    with pytest.raises(ValueError, match="同じ時刻"):
        expression_trace("CH1+CH2", [Trace("CH1", [0, 1], [1, 2]), Trace("CH2", [0, 2], [1, 2])])


def test_derivative_and_integral():
    t = np.linspace(0, 1, 101)
    trace = Trace("CH1", t, 3*t)
    np.testing.assert_allclose(transform(trace, "微分", "M").y, 3, atol=1e-10)
    assert transform(trace, "積分", "M").y[-1] == pytest.approx(1.5)
    np.testing.assert_allclose(transform(Trace("DC", t, np.ones(101)), "移動平均", "M", 12).y, 1)


def test_fft_frequency_and_peak_amplitude():
    t = np.arange(10000) / 10000
    f, amplitude = spectrum(Trace("CH1", t, 2.5*np.sin(2*np.pi*123*t)))
    index = np.argmax(amplitude)
    assert f[index] == pytest.approx(123)
    assert amplitude[index] == pytest.approx(2.5, rel=1e-5)


def test_fft_rejects_gaps_and_nonuniform_time():
    for trace in [Trace("CH1", [0, 1, 2], [0, np.nan, 1]), Trace("CH1", [0, 1, 3], [0, 1, 2])]:
        with pytest.raises(ValueError):
            spectrum(trace)
