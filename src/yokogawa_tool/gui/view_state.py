"""Validate saved axes against the data before applying them to a plot."""
import numpy as np


def waveform_bounds(traces):
    visible = [t for t in traces if t.visible]
    if not visible:
        return None
    x = (min(t.x[0] for t in visible), max(t.x[-1] for t in visible))
    values = [t.y[np.isfinite(t.y)] for t in visible]
    values = [y for y in values if len(y)]
    y = (min(v.min() for v in values), max(v.max() for v in values)) if values else (-1., 1.)
    return x, y


def usable_range(value):
    try:
        pair = np.asarray(value, dtype=float)
        return pair.shape == (2,) and bool(np.all(np.isfinite(pair))) and pair[1] > pair[0]
    except (TypeError, ValueError):
        return False


def restore_view(traces, view):
    """Keep useful zooms, recover invisible/out-of-data or extreme zoom-out views."""
    result = dict(view) if isinstance(view, dict) else {}
    visible = [t for t in traces if t.visible]
    if not visible:
        return result, False
    lo, hi = min(t.x[0] for t in visible), max(t.x[-1] for t in visible)
    reset = False
    if "x_range" in result:
        pair = result["x_range"]
        if usable_range(pair):
            pair = result["x_range"] = list(map(float, pair))
        if (not usable_range(pair) or pair[1] < lo or pair[0] > hi
                or pair[1]-pair[0] > (hi-lo)*20):
            result.pop("x_range", None)
            result.pop("y_range", None)
            reset = True
    if "y_range" in result:
        pair = result["y_range"]
        if usable_range(pair):
            pair = result["y_range"] = list(map(float, pair))
        finite = [t.y[np.isfinite(t.y)] for t in visible]
        finite = [y for y in finite if len(y)]
        if (not usable_range(pair) or (finite and
                (pair[1] < min(y.min() for y in finite) or pair[0] > max(y.max() for y in finite)))):
            result.pop("y_range", None)
            reset = True
    for key in ("cursor_a", "cursor_b"):
        if key in result:
            try:
                valid = np.isfinite(result[key]) and lo <= result[key] <= hi
            except (TypeError, ValueError):
                valid = False
            if not valid:
                result.pop(key)
    return result, reset
