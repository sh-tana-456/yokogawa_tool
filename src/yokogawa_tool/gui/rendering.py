"""Use a thin raster pen where dense transitions overdraw the same pixels."""
import numpy as np
import pyqtgraph as pg
from yokogawa_tool.core.interpolation import interpolate_display


def dense_transitions(x, y, x_range, y_range, width, height=600., *, budget=12000.):
    """Estimate stroke length in screen pixels, including sparse long edges."""
    if x is None or y is None or width <= 0 or height <= 0 or len(x) < 2:
        return False
    span = y_range[1] - y_range[0]
    x_span = x_range[1] - x_range[0]
    if not np.isfinite(span) or not np.isfinite(x_span) or span <= 0 or x_span <= 0:
        return False
    lo = max(0, np.searchsorted(x, x_range[0]) - 1)
    hi = min(len(x), np.searchsorted(x, x_range[1]) + 1)
    if hi - lo < 2:
        return False
    # Measure clipped screen-space travel. NaN gaps are not joined.
    values = np.clip(y[lo:hi], *y_range)
    dy = np.diff(values) * (height / span)
    dx = np.diff(np.clip(x[lo:hi], *x_range)) * (width / x_span)
    travel = np.hypot(dx, dy)
    return bool(np.sum(travel[np.isfinite(travel)]) > max(12000., width * 6) * budget / 12000.)


class AdaptiveCurveItem(pg.PlotCurveItem):
    dense = False

    def paint(self, painter, option, widget):
        view = self.getViewBox()
        self.dense = view is not None and dense_transitions(
            self.xData, self.yData, *view.viewRange(), view.width(), view.height(),
            budget=7800. if self.dense else 12000.)
        if not self.dense:
            return super().paint(painter, option, widget)
        # Keep the requested style intact, so zooming in restores smooth lines.
        aa, pen = self.opts['antialias'], self.opts['pen']
        thin = pg.mkPen(pen)
        thin.setWidthF(1.)
        self.opts['antialias'], self.opts['pen'] = False, thin
        try:
            return super().paint(painter, option, widget)
        finally:
            self.opts['antialias'], self.opts['pen'] = aa, pen


class WaveformPlotItem(pg.PlotDataItem):
    def __init__(self, *args, **kwargs):
        self.interpolation = 'linear'
        super().__init__()
        self.curve.setParentItem(None)
        self.curve = AdaptiveCurveItem()
        self.curve.setParentItem(self)
        self.curve.sigClicked.connect(self.sigClicked)
        self.setData(*args, **kwargs)

    def set_interpolation(self, mode):
        if mode not in ('linear', 'step', 'cubic'):
            raise ValueError('未対応の補間方法です。')
        self.interpolation = mode
        self.opts['stepMode'] = 'left' if mode == 'step' else None
        self.updateItems()

    def updateItems(self, styleUpdate=True):
        super().updateItems(styleUpdate)
        if self.interpolation == 'cubic':
            view = self.getViewBox()
            if view is not None:
                x, y = self.getData()
                xx, yy = interpolate_display(x, y, view.width())
                if xx is not x:
                    self.curve.setData(x=xx, y=yy)
