"""Bounded display-only monotone cubic interpolation, with explicit gaps."""
import numpy as np


def interpolate_display(x, y, width):
    if x is None or y is None or len(x) < 2 or width <= 0:
        return x, y
    factor = min(32, int(2 * width / len(x)))
    h = np.diff(x)
    # Peak-downsampled data has duplicate X: never smooth that envelope.
    if factor <= 1 or not np.all(h > 0):
        return x, y
    u = np.arange(factor) / factor
    xx = np.r_[(x[:-1, None] + h[:, None] * u).ravel(), x[-1]]
    yy = np.full(len(xx), np.nan)
    yy[::factor] = y
    valid = np.isfinite(y)
    changes = np.diff(np.r_[False, valid, False].astype(int))
    for start, end in zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)):
        if end - start < 2:
            continue
        values = y[start:end]
        steps = np.diff(x[start:end])
        secants = np.diff(values) / steps
        slopes = np.zeros(len(values))
        if len(values) == 2:
            slopes[:] = secants[0]
        else:
            same = (np.sign(secants[:-1]) == np.sign(secants[1:])) & (secants[:-1] != 0)
            w1, w2 = 2 * steps[1:] + steps[:-1], steps[1:] + 2 * steps[:-1]
            indices = np.flatnonzero(same)
            slopes[indices + 1] = (w1[indices] + w2[indices]) / (
                w1[indices] / secants[indices] + w2[indices] / secants[indices + 1])
            def endpoint(h0, h1, d0, d1):
                value = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
                if np.sign(value) != np.sign(d0):
                    return 0.
                if np.sign(d0) != np.sign(d1) and abs(value) > abs(3 * d0):
                    return 3 * d0
                return value
            slopes[0] = endpoint(*steps[:2], *secants[:2])
            slopes[-1] = endpoint(*steps[-2:][::-1], *secants[-2:][::-1])
        result = ((2*u**3 - 3*u**2 + 1) * values[:-1, None]
            + (u**3 - 2*u**2 + u) * (steps * slopes[:-1])[:, None]
            + (-2*u**3 + 3*u**2) * values[1:, None]
            + (u**3 - u**2) * (steps * slopes[1:])[:, None])
        yy[start*factor:(end-1)*factor] = result.ravel()
        yy[(end-1)*factor] = values[-1]
    return xx, yy
