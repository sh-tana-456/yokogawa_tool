import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import numpy as np
from PySide6 import QtCore, QtWidgets as W
from yokogawa_tool.gui.instrument_panel import InstrumentPanel
from yokogawa_tool.core.waveform import Trace
from test_panel_sync import DATA
from test_instrument_settings import SettingsScope


def test_setting_rate_is_queried_separately_from_record_rate():
    scope = SettingsScope()
    result = scope.read_settings()
    assert result['sample_rate'] == '1e6'
    assert ':TIMEBASE:SRATE?' in scope.queries
    assert not scope.commands


def test_summary_distinguishes_settings_record_and_selected_channel(tmp_path):
    app = W.QApplication.instance() or W.QApplication([])
    settings = QtCore.QSettings(str(tmp_path/'sampling.ini'), QtCore.QSettings.IniFormat)
    panel = InstrumentPanel(settings)
    requests = []
    panel.requested.connect(lambda *args: requests.append(args))
    data = dict(DATA, sample_rate='20e6', tdiv='50e-6')
    try:
        panel.update_settings(data)
        trace = Trace('CH1', np.arange(10020)/2e6, np.zeros(10020), metadata={
            'sample_rate': 2e6, 'timebase_sample_rate': 20e6, 'time_div': 50e-6, 'vertical_div': .5})
        panel.update_waveform_info([trace])
        lines = panel.acquisition_info.text().splitlines()
        assert '20 MSa/s' in lines[0] and '50 µs' in lines[0]
        assert 'CH1 V/div' in lines[1] and '500 mV' in lines[1] and '10 k' in lines[1]
        assert '10020 pts' in lines[2] and '2 MSa/s' in lines[2]
        assert not requests  # Readouts must not generate device setting writes.
        height = panel.acquisition_info.height()
        panel.channel.setCurrentIndex(2)
        assert panel.acquisition_info.text().splitlines()[1].startswith('CH3 V/div: —')
        panel.update_settings(data)  # Late CH1 reply cannot become CH3 settings.
        assert panel.acquisition_info.text().splitlines()[1].startswith('CH3 V/div: —')
        assert panel.acquisition_info.height() == height
        panel.update_settings(dict(data, probe='C10'))
        panel.channel.setCurrentIndex(0)
        panel.update_waveform_info([trace])
        assert 'CH1 A/div' in panel.acquisition_info.text()
        panel.invalidate()
        assert 'MSa/s' not in panel.acquisition_info.text()
    finally:
        panel.invalidate()
        panel.close()
