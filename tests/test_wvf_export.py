"""Export precision, independent layout checks, and paired-file failure safety."""
from pathlib import Path
import struct
import numpy as np
import pytest
from yokogawa_tool.core.waveform import Trace, export_wvf, read_wvf, wvf_paths


@pytest.mark.parametrize("number", range(6))
def test_export_synthetic_samples_without_vertical_quantization(tmp_path, number):
    source = Path(__file__).resolve().parents[1] / "demo" / f"{number:04}.WVF"
    traces = read_wvf(source)
    wave, header = export_wvf(tmp_path / "export.WVF", traces)
    restored = read_wvf(header)
    assert [t.name for t in restored] == [t.name for t in traces]
    assert wave.stat().st_size == sum(t.y.nbytes for t in traces)
    for before, after in zip(traces, restored):
        np.testing.assert_array_equal(after.y, before.y)
        np.testing.assert_allclose(after.x, before.x, rtol=0, atol=1e-15)
        assert after.unit == before.unit


def test_export_fs8_layout_nan_and_independent_sampling_grids(tmp_path):
    traces = [Trace("CH1", [-1, 0, 1], [1.2345678901234567, np.nan, -1e200], visible=False),
              Trace("MATH1", [.25, .75], [np.inf, -np.inf], "arb")]
    wave, header = export_wvf(tmp_path / "data", traces)
    assert wave.name == "data.WVF" and header.name == "data.HDR"
    assert "VDataType FS8" in header.read_text()
    raw = struct.unpack(">5d", wave.read_bytes())
    assert raw[0] == traces[0].y[0] and np.isnan(raw[1]) and raw[2] == -1e200
    assert raw[3:] == (np.inf, -np.inf)
    restored = read_wvf(wave)
    for before, after in zip(traces, restored):
        np.testing.assert_array_equal(after.y, before.y)
        np.testing.assert_array_equal(after.x, before.x)


@pytest.mark.parametrize("traces", [[], [Trace("CH1", [0, 1, 3], [1, 2, 3])],
    [Trace("bad name", [0, 1], [1, 2])], [Trace("波形", [0, 1], [1, 2])],
    [Trace("CH1", [0, 1], [1, 2]), Trace("CH1", [0, 1], [3, 4])]])
def test_invalid_export_preserves_existing_pair(tmp_path, traces):
    wave, header = tmp_path / "data.wvf", tmp_path / "data.hdr"
    wave.write_bytes(b"old wave"); header.write_bytes(b"old header")
    with pytest.raises(ValueError):
        export_wvf(wave, traces)
    assert wave.read_bytes() == b"old wave" and header.read_bytes() == b"old header"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["data.hdr", "data.wvf"]


def test_failed_pair_replace_rolls_back_both_files(tmp_path, monkeypatch):
    import yokogawa_tool.core.waveform as module
    wave, header = tmp_path / "data.WVF", tmp_path / "data.hdr"
    wave.write_bytes(b"old wave"); header.write_bytes(b"old header")
    original_replace = module.os.replace
    def fail_header(source, destination):
        if Path(source).name == "header":
            raise OSError("disk failure")
        return original_replace(source, destination)
    monkeypatch.setattr(module.os, "replace", fail_header)
    with pytest.raises(OSError, match="disk failure"):
        export_wvf(wave, [Trace("CH1", [0, 1], [1, 2])])
    assert wave.read_bytes() == b"old wave" and header.read_bytes() == b"old header"
    assert wvf_paths(tmp_path / "data.HDR") == (wave, header)
