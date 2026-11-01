#!/usr/bin/env python3
"""Render the app with synthetic inputs; do not connect to any instrument."""
from pathlib import Path
import socket
import sys
import tempfile
import numpy as np
from PySide6 import QtCore, QtWidgets as W

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from yokogawa_tool.gui.app import MainWindow, configure_application
from yokogawa_tool.core.waveform import Trace


def no_network(*args, **kwargs):
    raise OSError('Network disabled for synthetic screenshots')


socket.create_connection = no_network
with tempfile.TemporaryDirectory(prefix='yokogawa-screenshot-settings-') as settings:
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
    QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, settings)
    app = W.QApplication([])
    configure_application(app)
    window = MainWindow()
    errors = []
    window.error = errors.append
    window.resize(1440, 1000)
    window.open_path(ROOT/'demo/0000.WVF')
    window.show()

    def save(name):
        app.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        app.processEvents()
        assert not errors, errors
        assert window.grab().save(str(ROOT/'docs'/name))

    save('workbench.png')
    window.apply_theme('xp')
    save('python-xp.png')
    window.apply_theme('dark')
    panel = window.instrument_panel
    panel.update_settings(dict(identity='SYNTHETIC DEMO - no instrument connected', running=False,
        channel=1, tdiv='.001', sample_rate='1000000', record_length='10000', high_resolution='0',
        acquire_mode='NORM', trigger_mode='AUTO', trigger_type='SIMP', display='1', probe='10',
        vdiv='.5', offset='0', position='0', coupling='DC', bandwidth='FULL', invert='0',
        source='1', slope='RISE', level='0', delay='0'))
    panel.details_toggle.setChecked(True)
    window.sidebar_tabs.blockSignals(True)
    window.sidebar_tabs.setCurrentIndex(1)
    window.sidebar_tabs.blockSignals(False)
    save('python-instrument.png')
    window.sidebar_tabs.setCurrentIndex(0)
    window.apply_theme('xp')
    x = np.linspace(-1e-5, 1e-5, 4008)
    window.set_traces([Trace('CH1', x, 2+.1*np.sin(2*np.pi*150000*x), metadata={'source':'synthetic'})],
                      'Synthetic zoom recovery', dict(x_range=[-.05, .03], cursor_a=-.027))
    save('session-recovered.png')
    window.dirty = False
    panel.invalidate()
    window.close()
    print('Generated four synthetic application screenshots with network access disabled.')
