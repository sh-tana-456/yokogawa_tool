from pathlib import Path
import struct
import numpy as np
import pytest
from yokogawa_tool.core.waveform import (read_wvf, Trace, export_csv, read_csv,
                                    save_session, load_session)

SAMPLES = Path(__file__).resolve().parents[1] / "demo"


@pytest.mark.parametrize("number,channels,dt,t0", [
    (0, ["CH1", "CH2", "CH3"], 1e-6, -.005),
    (1, ["CH1", "CH2", "CH3"], 2e-6, -.01),
    (2, ["CH2", "CH3"], 2e-6, -.01),
    (3, ["CH1", "CH2", "CH3"], 1e-7, -.0005),
    (4, ["CH2"], 1e-6, -.005),
    (5, ["CH2"], 2e-6, -.01),
])
def test_synthetic_samples(number, channels, dt, t0):
    path = SAMPLES / f"{number:04}.WVF"
    traces = read_wvf(path)
    assert [t.name for t in traces] == channels
    raw = path.read_bytes()
    for ch, trace in enumerate(traces):
        assert len(trace.y) == 10020
        assert trace.x[0] == t0
        assert trace.x[-1] == pytest.approx(t0 + 10019 * dt)
        # Independent struct decoding verifies channel-contiguous layout and scale.
        for i in (0, 37, 5010, 10019):
            value = struct.unpack_from(">h", raw, (ch * 10020 + i) * 2)[0]
            if value != 32767:
                assert trace.y[i] == pytest.approx(value * 1.6276042e-4)


def write_pair(tmp_path, endian="Ltl", order="Trace", blocks=2, truncate=False):
    header = f"""$PublicInfo
Endian {endian}
DataFormat {order}
DataOffset 4
GroupNumber 1
TraceTotalNumber 2
$Group1
TraceNumber 2
BlockNumber {blocks}
TraceName CH1 CH2
BlockSize 3 3
VResolution 0.5 2
VOffset 1 -1
VDataType IS2 IS2
VUnit V A
HUnit s s
HResolution 0.1 0.1
HOffset -0.1 -0.1
VIllegalData 32767 32767
"""
    (tmp_path / "Test.hdr").write_text(header)
    pairs = [(c, b) for c in range(2) for b in range(blocks)] if order == "Trace" else [(c, b) for b in range(blocks) for c in range(2)]
    raw = b"abcd" + b"".join(struct.pack(("<" if endian == "Ltl" else ">")+"3h", c*100+b*10, 2, 32767) for c, b in pairs)
    (tmp_path / "Test.wvf").write_bytes(raw[:-1] if truncate else raw)
    return tmp_path / "Test.wvf"


@pytest.mark.parametrize("endian,order", [("Big", "Trace"), ("Ltl", "Trace"), ("Big", "Block"), ("Ltl", "Block")])
def test_block_layout_and_invalid_samples(tmp_path, endian, order):
    traces = read_wvf(write_pair(tmp_path, endian, order))
    assert [t.name for t in traces] == ["CH1_B1", "CH1_B2", "CH2_B1", "CH2_B2"]
    np.testing.assert_allclose([t.y[0] for t in traces], [1, 6, 199, 219])
    assert all(np.isnan(t.y[2]) for t in traces)


def test_truncated_wvf(tmp_path):
    with pytest.raises(ValueError, match="不足"):
        read_wvf(write_pair(tmp_path, truncate=True))


def test_missing_header(tmp_path):
    (tmp_path / "empty.wvf").touch()
    with pytest.raises(ValueError, match="見つかりません"):
        read_wvf(tmp_path / "empty.wvf")


def test_session_is_self_contained(tmp_path):
    traces = read_wvf(SAMPLES / "0000.WVF")
    traces[1].color, traces[1].visible = "#123456", False
    path = tmp_path / "test.scope.npz"
    view = {"cursor_a": -.001, "cursor_b": .002, "x_range": [-.002, .004]}
    save_session(path, traces, view)
    restored, restored_view = load_session(path)
    assert restored_view == view
    assert restored[1].color == "#123456" and not restored[1].visible
    for before, after in zip(traces, restored):
        np.testing.assert_array_equal(before.x, after.x)
        np.testing.assert_array_equal(before.y, after.y)


def test_csv_different_grids_preserve_samples(tmp_path):
    traces = [Trace("CH1", [0, 1, 2], [1, np.nan, 3]), Trace("CH2", [.5, 1.5], [9, 8], "A")]
    path = tmp_path / "test.csv"
    export_csv(path, traces)
    restored = read_csv(path)
    for t, r in zip(traces, restored):
        np.testing.assert_equal(r.y[np.searchsorted(r.x, t.x)], t.y)
        assert r.unit == t.unit
    assert np.isnan(restored[1].y[0])


def test_nearest_no_extrapolation():
    trace = Trace("CH1", [0, 1, 2], [3, 4, 5])
    assert trace.nearest(.8) == (1, 4)
    assert np.isnan(trace.nearest(-1)[1])


def test_invalid_time_axis():
    with pytest.raises(ValueError):
        Trace("CH1", [0, 0, 1], [1, 2, 3])


def test_portable_json_session_roundtrip(tmp_path):
    traces = [Trace("CH1", [0, 1, 2], [1, np.nan, 3], color="#123456", visible=False)]
    view = {"cursor_a": 0, "cursor_b": 2, "x_range": [0, 2]}
    path = tmp_path / "portable.scope.json"
    save_session(path, traces, view)
    assert '"format": "dl1640-scope"' in path.read_text()
    assert "null" in path.read_text() and "NaN" not in path.read_text()
    restored, actual_view = load_session(path)
    np.testing.assert_array_equal(restored[0].y, traces[0].y)
    assert actual_view == view and not restored[0].visible and restored[0].color == "#123456"
