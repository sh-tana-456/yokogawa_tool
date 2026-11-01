"""Waveform I/O. WVF decoding follows IM701610-01E, Appendix 3."""
from dataclasses import dataclass, field
from pathlib import Path
import csv
import json
import os
import tempfile
import numpy as np

COLORS = ["#f8d66d", "#53c5f7", "#f28bb5", "#70dfb0", "#b59aff", "#ffac70"]


@dataclass
class Trace:
    name: str
    x: np.ndarray
    y: np.ndarray
    unit: str = "V"
    color: str = COLORS[0]
    visible: bool = True
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        self.x = np.asarray(self.x, dtype=float)
        self.y = np.asarray(self.y, dtype=float)
        if (self.x.ndim != 1 or self.y.shape != self.x.shape or len(self.x) < 2
                or not np.all(np.isfinite(self.x)) or not np.all(np.diff(self.x) > 0)):
            raise ValueError(f"{self.name}: 時刻は昇順で2点以上、値と同じ長さが必要です。")

    def nearest(self, time):
        if time < self.x[0] or time > self.x[-1]:
            return float("nan"), float("nan")
        i = int(np.searchsorted(self.x, time))
        if i and (i == len(self.x) or time - self.x[i - 1] <= self.x[i] - time):
            i -= 1
        return float(self.x[i]), float(self.y[i])


def companion(path: Path, suffix: str) -> Path:
    for p in path.parent.iterdir():
        if p.stem.lower() == path.stem.lower() and p.suffix.lower() == suffix.lower():
            return p
    raise ValueError(f"{path.stem}{suffix} が見つかりません。同じフォルダにWVFとHDRを置いてください。")


def read_wvf(path: str | Path) -> list[Trace]:
    path = Path(path)
    header_path = companion(path, ".hdr")
    wave_path = companion(path, ".wvf")
    sections = {}
    section = None
    for line in header_path.read_text(encoding="ascii").splitlines():
        line = line.strip()
        if line.startswith("$"):
            section = sections.setdefault(line[1:].lower(), {})
        elif section is not None and line and not line.startswith("//"):
            parts = line.split()
            section[parts[0]] = parts[1:]
    try:
        public = sections["publicinfo"]
        endian = {"Big": ">", "Ltl": "<"}[public["Endian"][0]]
        order = public["DataFormat"][0]
        if order not in ("Trace", "Block"):
            raise ValueError(f"未対応のDataFormat: {order}")
        raw = wave_path.read_bytes()
        offset = int(public["DataOffset"][0])
        if offset < 0 or offset > len(raw):
            raise ValueError("DataOffsetがファイルの範囲外です。")
        traces = []
        for group_no in range(1, int(public["GroupNumber"][0]) + 1):
            group = sections[f"group{group_no}"]
            count = int(group["TraceNumber"][0])
            blocks = int(group["BlockNumber"][0])
            if count < 1 or blocks < 1 or count * blocks > 10000:
                raise ValueError("不正なTraceNumber/BlockNumberです。")
            decoded = {}
            pairs = ([(ch, b) for ch in range(count) for b in range(blocks)]
                     if order == "Trace" else
                     [(ch, b) for b in range(blocks) for ch in range(count)])
            for ch, block in pairs:
                dtype = np.dtype(endian + {"IS2": "i2", "IS1": "i1", "IU2": "u2",
                                          "IU1": "u1", "RF4": "f4", "RF8": "f8",
                                          "FS4": "f4", "FS8": "f8"}[group["VDataType"][ch]])
                size = int(group["BlockSize"][ch])
                end = offset + size * dtype.itemsize
                if size < 2 or end > len(raw):
                    raise ValueError("WVFデータがHDRのBlockSizeに対して不足しています。")
                values = np.frombuffer(raw, dtype=dtype, count=size, offset=offset).astype(float)
                offset = end
                invalid = np.zeros(size, dtype=bool)
                for key in ("VIllegalData", "VPlusOverData", "VMinusOverData"):
                    if key in group:
                        marker = float(group[key][ch])
                        invalid |= ((values >= marker) if key == "VPlusOverData" else
                                    (values <= marker) if key == "VMinusOverData" else values == marker)
                values = values * float(group["VResolution"][ch]) + float(group["VOffset"][ch])
                values[invalid] = np.nan
                if group["HUnit"][ch].lower() != "s":
                    raise ValueError("時間軸が秒以外のWVFは未対応です。FFTはアプリ内で計算できます。")
                dt, t0 = float(group["HResolution"][ch]), float(group["HOffset"][ch])
                if not np.isfinite(dt) or dt <= 0:
                    raise ValueError("HResolutionは正の有限値が必要です。")
                name = group["TraceName"][ch]
                if blocks > 1:
                    name += f"_B{block + 1}"
                color_index = int(name[2]) - 1 if name.startswith("CH") and name[2:3].isdigit() else len(traces)
                decoded[ch, block] = Trace(name, t0 + np.arange(size) * dt, values,
                    group["VUnit"][ch], COLORS[color_index % len(COLORS)], metadata={
                        "source": str(wave_path), "block": block + 1,
                        "sample_rate": 1 / dt, "vertical_offset": float(group["VOffset"][ch]),
                        "vertical_resolution": float(group["VResolution"][ch]),
                        "date": group.get("Date", [""] * count)[ch],
                        "time": group.get("Time", [""] * count)[ch],
                        "model": public.get("Model", [""])[0]})
            traces.extend(decoded[ch, b] for ch in range(count) for b in range(blocks))
        if len({t.name for t in traces}) != len(traces):
            raise ValueError("重複するトレース名があります。")
        # DL1600 stores private instrument setup data after waveform samples.
        return traces
    except (KeyError, IndexError) as exc:
        raise ValueError(f"HDRの項目が不足、または未対応のデータ形式です: {exc}") from exc


def read_csv(path: str | Path) -> list[Trace]:
    """CSV columns: time_s, CH1[V], CH2[V], ...; optional header."""
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = [row for row in csv.reader(stream) if row and not row[0].startswith("#")]
    if not rows:
        raise ValueError("CSVが空です。")
    try:
        float(rows[0][0])
        header = ["time_s"] + [f"CH{i}" for i in range(1, len(rows[0]))]
    except ValueError:
        header = rows.pop(0)
    try:
        data = np.asarray(rows, dtype=float)
    except ValueError as exc:
        raise ValueError("CSVは時刻[s]と各CHの数値をカンマ区切りで指定してください。") from exc
    if data.ndim != 2 or data.shape[1] < 2 or data.shape[1] != len(header):
        raise ValueError("CSVの列数が不正です。先頭列に時刻[s]が必要です。")
    result = []
    for i, title in enumerate(header[1:]):
        name, _, unit = title.partition("[")
        result.append(Trace(name.strip() or f"CH{i+1}", data[:, 0], data[:, i+1],
                            unit.rstrip("]") if unit else "V", COLORS[i % len(COLORS)],
                            metadata={"source": str(path)}))
    return result


def export_csv(path, traces):
    if not traces:
        raise ValueError("出力する波形がありません。")
    # Keep each trace's sampling grid intact, using blank/NaN at absent timestamps.
    x = np.unique(np.concatenate([t.x for t in traces]))
    columns = [x]
    for trace in traces:
        y = np.full(len(x), np.nan)
        y[np.searchsorted(x, trace.x)] = trace.y
        columns.append(y)
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time_s"] + [f"{t.name}[{t.unit}]" for t in traces])
        writer.writerows(zip(*columns))


def wvf_paths(path):
    path = Path(path)
    if path.suffix.lower() not in (".wvf", ".hdr"):
        path = path.with_suffix(".WVF")
    wave_path = path if path.suffix.lower() == ".wvf" else path.with_suffix(".WVF")
    header_path = path if path.suffix.lower() == ".hdr" else path.with_suffix(".HDR")
    # Use an existing companion's spelling on case-sensitive filesystems.
    for suffix in (".wvf", ".hdr"):
        try:
            existing = companion(path, suffix)
        except ValueError:
            continue
        if suffix == ".wvf":
            wave_path = existing
        else:
            header_path = existing
    return wave_path, header_path


def export_wvf(path, traces):
    """PC interchange pair: big-endian FS8, one independent group per trace.

    This does not create DL1640's private setup/recall data. No integer
    quantization or resampling is performed; X is represented by start/step.
    """
    if not traces:
        raise ValueError("出力する波形がありません。")
    wave_path, header_path = wvf_paths(path)
    lines = ["//YOKOGAWA ASCII FILE FORMAT", "", "$PublicInfo", "FormatVersion 1.11",
             "Model YOKOGAWA_TOOL", "Endian Big", "DataFormat Trace",
             f"GroupNumber {len(traces)}", f"TraceTotalNumber {len(traces)}", "DataOffset 0"]
    names = set()
    for i, trace in enumerate(traces, 1):
        for label, value in (("CH名", trace.name), ("単位", trace.unit)):
            if not value or not value.isascii() or any(c.isspace() or ord(c) < 33 for c in value):
                raise ValueError(f"{label}は空白を含まないASCII文字にしてください。CSV/NPZでは元の名前を使用できます。")
        if trace.name in names:
            raise ValueError("CH名が重複しています。")
        names.add(trace.name)
        dt = (trace.x[-1] - trace.x[0]) / (len(trace.x) - 1)
        expected = trace.x[0] + np.arange(len(trace.x)) * dt
        tolerance = max(abs(dt) * 1e-7, abs(np.spacing(np.max(np.abs(trace.x)))) * 4)
        if not np.isfinite(dt) or dt <= 0 or not np.allclose(trace.x, expected, rtol=0, atol=tolerance):
            raise ValueError(f"{trace.name}: WVF/HDRには等間隔の時間軸が必要です。CSVまたはNPZを使用してください。")
        lines += ["", f"$Group{i}", "TraceNumber 1", "BlockNumber 1",
                  f"TraceName {trace.name}", f"BlockSize {len(trace.y)}", "VResolution 1",
                  "VOffset 0", "VDataType FS8", f"VUnit {trace.unit}",
                  f"HResolution {dt:.17g}", f"HOffset {trace.x[0]:.17g}", "HUnit s"]
    # Validate and stage both files before replacing either destination.
    with tempfile.TemporaryDirectory(prefix=".wvf-export-", dir=wave_path.parent) as directory:
        staged_wave = Path(directory) / "wave"
        staged_header = Path(directory) / "header"
        with staged_wave.open("wb") as stream:
            for trace in traces:
                stream.write(np.asarray(trace.y, dtype=">f8").tobytes())
        staged_header.write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))
        # Keep old files available for rollback if the second replace fails.
        backups, installed = [], []
        try:
            for index, target in enumerate((wave_path, header_path)):
                if target.exists():
                    backup = Path(directory) / f"backup{index}"
                    os.replace(target, backup)
                    backups.append((target, backup))
            for staged, target in ((staged_wave, wave_path), (staged_header, header_path)):
                os.replace(staged, target)
                installed.append(target)
        except OSError:
            for target in installed:
                target.unlink()
            for target, backup in backups:
                os.replace(backup, target)
            raise
    return wave_path, header_path


def save_session(path, traces, view=None):
    if str(path).lower().endswith(".json"):
        def finite(values):
            return [float(v) if np.isfinite(v) else None for v in values]
        data = {"format": "dl1640-scope", "version": 1, "view": view or {}, "traces": [
            dict(name=t.name, x=finite(t.x), y=finite(t.y), unit=t.unit, color=t.color,
                 visible=t.visible, metadata=t.metadata) for t in traces]}
        Path(path).write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        return
    meta = {"version": 1, "view": view or {}, "traces": [dict(name=t.name, unit=t.unit,
            color=t.color, visible=t.visible, metadata=t.metadata) for t in traces]}
    arrays = {f"{axis}{i}": getattr(t, axis) for i, t in enumerate(traces) for axis in ("x", "y")}
    with Path(path).open("wb") as stream:
        np.savez_compressed(stream, metadata=json.dumps(meta, ensure_ascii=False), **arrays)


def load_session(path):
    if str(path).lower().endswith(".json"):
        meta = json.loads(Path(path).read_text(encoding="utf-8"))
        if meta.get("format") != "dl1640-scope" or meta.get("version") != 1:
            raise ValueError("未対応のセッション形式です。")
        traces = [Trace(**info) for info in meta["traces"]]
        if len({t.name for t in traces}) != len(traces):
            raise ValueError("CH名が重複しています。")
        return traces, meta.get("view", {})
    with np.load(path, allow_pickle=False) as archive:
        meta = json.loads(str(archive["metadata"]))
        if meta["version"] != 1:
            raise ValueError("未対応のセッション形式です。")
        traces = [Trace(x=archive[f"x{i}"], y=archive[f"y{i}"], **info)
                  for i, info in enumerate(meta["traces"])]
    return traces, meta.get("view", {})


def load_file(path):
    path = Path(path)
    if path.name.lower().endswith((".npz", ".json")):
        return load_session(path)
    if path.suffix.lower() in (".wvf", ".hdr"):
        return read_wvf(path), {}
    if path.suffix.lower() == ".csv":
        return read_csv(path), {}
    raise ValueError("WVF/HDR、CSV、または.scope.npzを選択してください。")
