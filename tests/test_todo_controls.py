import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import numpy as np
from PySide6 import QtCore, QtWidgets as W, QtTest
from yokogawa_tool.gui.app import MainWindow, configure_application
from yokogawa_tool.gui.instrument_panel import InstrumentPanel
from yokogawa_tool.gui.protocol_panel import ProtocolDialog
from yokogawa_tool.protocols import Annotation
from yokogawa_tool.core.waveform import Trace


def application():
    app = W.QApplication.instance() or W.QApplication([])
    configure_application(app)
    return app


def test_interval_persistence_details_and_preview_only(tmp_path):
    app = application()
    settings = QtCore.QSettings(str(tmp_path/'settings.ini'), QtCore.QSettings.IniFormat)
    panel = InstrumentPanel(settings)
    panel.live_interval.setValue(700)
    assert panel.details.isHidden()
    panel.details_toggle.setChecked(True)
    assert not panel.details.isHidden()
    assert panel.live_mode.count() == 1 and panel.live_mode.currentData() is True
    restored = InstrumentPanel(settings)
    assert restored.live_interval.value() == 700
    panel.close(); restored.close()


def test_dark_plot_override_preserves_light_ui_and_original_data():
    app = application()
    window = MainWindow()
    original_theme, original_dark = window.theme_combo.currentData(), window.dark_plot.isChecked()
    y = np.arange(10.)
    try:
        window.set_traces([Trace('CH1', np.arange(10.), y)], 'Theme')
        window.dark_plot.setChecked(True)
        window.apply_theme('light')
        assert window.theme_combo.currentData() == 'light'
        assert window.plot.backgroundBrush().color().name() == '#101720'
        window.dark_plot.setChecked(False)
        assert window.plot.backgroundBrush().color().name() == '#ffffff'
        np.testing.assert_array_equal(window.traces[0].y, y)
    finally:
        window.dark_plot.setChecked(original_dark)
        window.apply_theme(original_theme)
        window.dirty = False; window.close()


def test_protocol_dialog_snapshot_result_export_and_zoom(tmp_path, monkeypatch):
    app = application()
    parent = MainWindow()
    saved = parent.settings.value('sigrok_cli', None)
    parent.set_traces([Trace('CH1', np.linspace(0, 1, 1000), np.zeros(1000))], 'Snapshot')
    dialog = ProtocolDialog(parent.traces, parent.settings, parent)
    try:
        for protocol in ('spi', 'i2c', 'can', 'uart'):
            dialog.protocol.setCurrentIndex(dialog.protocol.findData(protocol))
        event = Annotation(.1, .2, 'RX', 'A5')
        monkeypatch.setattr('yokogawa_tool.gui.protocol_panel.decode', lambda *args: [event])
        dialog.start_decode()
        for _ in range(100):
            QtTest.QTest.qWait(10)
            if dialog.worker is None:
                break
        assert dialog.worker is None and dialog.run.isEnabled()
        assert dialog.table.item(0, 3).text() == 'A5'
        dialog.zoom_event(0, 0)
        np.testing.assert_allclose(parent.plot.viewRange()[0], [.1, .2])
        path = tmp_path/'events.csv'
        monkeypatch.setattr(W.QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
        dialog.export()
        assert 'start_s,end_s,kind,text' in path.read_text() and 'A5' in path.read_text()
    finally:
        if saved is None: parent.settings.remove('sigrok_cli')
        else: parent.settings.setValue('sigrok_cli', saved)
        dialog.close(); parent.dirty = False; parent.close()


def test_display_restore_failure_is_reported_from_worker_thread():
    import threading
    app = application()
    window = MainWindow()
    class Context:
        display_restore_error = 'LCD復元失敗のテスト'
        def __exit__(self, *args): pass
    context = Context()
    try:
        window._live_device = ({}, context, context)
        thread = threading.Thread(target=window.close_live_device)
        thread.start(); thread.join(1)
        assert not thread.is_alive() and window._live_device is None
        app.processEvents()
        assert window.network_label.text() == context.display_restore_error
    finally:
        window.dirty = False; window.close()
