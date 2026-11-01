"""Aligned analog samples to thresholded logic bits; no resampling."""
import numpy as np


def logic_data(channels, thresholds):
    traces = list(channels.values())
    if not traces or len(traces) > 8:
        raise ValueError('解析するCHを選択してください。')
    base = traces[0]
    intervals = np.diff(base.x)
    dt = float(intervals[0])
    if not np.isfinite(dt) or dt <= 0:
        raise ValueError("サンプル間隔が不正です。")
    if not np.allclose(intervals, dt, rtol=1e-6, atol=dt*1e-8):
        raise ValueError('プロトコル解析には等間隔の元サンプルが必要です。')
    packed = np.zeros(len(base.x), dtype=np.uint8)
    for bit, (role, trace) in enumerate(channels.items()):
        if trace.x.shape != base.x.shape or not np.allclose(trace.x, base.x, rtol=0, atol=dt*1e-6):
            raise ValueError('解析するCHは同じサンプル時刻の波形を選択してください。')
        if not np.all(np.isfinite(trace.y)):
            raise ValueError('欠損を含む波形は復号できません。欠損のない記録を選んでください。')
        threshold = thresholds[role]
        if not np.isfinite(threshold):
            raise ValueError('しきい値は有限値にしてください。')
        packed |= (trace.y >= threshold).astype(np.uint8) << bit
    return packed, dt, float(base.x[0])


