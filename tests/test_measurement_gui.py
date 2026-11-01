import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import numpy as np
from PySide6.QtWidgets import QApplication
from yokogawa_tool.gui.app import MainWindow, configure_application, fmt
from yokogawa_tool.core.measurements import METRICS
from yokogawa_tool.core.waveform import Trace


def test_selection_ranges_and_restore_settings():
    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    saved = window.settings.value('measurement_items', None)
    try:
        x = np.linspace(0, 1, 1001)
        y = np.where(x < .5, 1., 5.)
        window.set_traces([Trace('CH1', x, y)], 'measurement test')
        for key, action in window.measurement_actions.items():
            action.setChecked(key in ('mean', 'std'))
        window.plot.setXRange(0, .4, padding=0)
        window.update_readouts()
        mean_col = 6 + [m.key for m in METRICS].index('mean')
        std_col = 6 + [m.key for m in METRICS].index('std')
        assert not window.table.isColumnHidden(std_col) and window.table.isColumnHidden(6)
        assert window.table.item(0, mean_col).text() == fmt(1, 'V')
        window.visible_stats.setChecked(False)
        window.update_readouts()
        assert window.table.item(0, mean_col).text() == fmt(np.mean(y), 'V')
        window.cursor_a.setValue(.6); window.cursor_b.setValue(.9)
        window.measure_ab.setChecked(True)
        window.update_readouts()
        assert not window.visible_stats.isEnabled()
        assert window.table.item(0, mean_col).text() == fmt(5, 'V')
        assert window.table.item(0, std_col).text() == fmt(0, 'V')
        assert window.settings.value('measurement_items') == ['mean', 'std']
        np.testing.assert_array_equal(window.traces[0].y, y)
    finally:
        if saved is None:
            window.settings.remove('measurement_items')
        else:
            window.settings.setValue('measurement_items', saved)
        window.dirty = False
        window.close()
