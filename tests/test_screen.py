import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import struct
import numpy as np
import pytest
from PySide6 import QtCore, QtGui, QtWidgets as W, QtTest
from yokogawa_tool.acquisition import screen
from yokogawa_tool.gui.app import MainWindow, configure_application
from yokogawa_tool.core.waveform import Trace


@pytest.fixture
def png():
    image = QtGui.QImage(64, 48, QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor("#d0aa00"))
    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(buffer.data())


def fake_server(monkeypatch, data):
    requests = []
    @contextmanager
    def open_request(request, timeout):
        requests.append((request, timeout))
        yield SimpleNamespace(read=lambda size: data[:size])
    monkeypatch.setattr(screen, "build_opener", lambda *handlers: SimpleNamespace(open=open_request))
    return requests


def test_http_monitor_uses_only_get_and_validates_png(monkeypatch, png):
    requests = fake_server(monkeypatch, png)
    result = screen.fetch_screen("10.0.10.14", port=8080)
    assert result["png"] == png and result["seconds"] >= 0
    request, timeout = requests[0]
    assert request.get_method() == "GET" and request.data is None
    assert request.full_url == "http://10.0.10.14:8080/webmonimage.png"
    assert timeout == 20 and len(requests) == 1
    assert request.get_header("Cache-control") == "no-cache"


@pytest.mark.parametrize("payload", [b"<html>login required</html>", b"", b"x"*(8*1024*1024+1)])
def test_http_monitor_rejects_nonimages_and_oversized_responses(monkeypatch, payload):
    fake_server(monkeypatch, payload)
    with pytest.raises(ValueError):
        screen.fetch_screen("scope")


def test_http_monitor_rejects_invalid_dimensions_and_redirect(monkeypatch, png):
    invalid = png[:16] + struct.pack(">II", 100000, 100000) + png[24:]
    fake_server(monkeypatch, invalid)
    with pytest.raises(ValueError, match="サイズ"):
        screen.fetch_screen("scope")
    with pytest.raises(ValueError, match="リダイレクト"):
        screen.NoRedirect().redirect_request(None, None, 302, "Found", None, "http://other/")


@pytest.mark.parametrize("host", ["", "http://scope", "scope/private", "scope@other", "scope\nother"])
def test_http_monitor_rejects_url_instead_of_hostname(host):
    with pytest.raises(ValueError):
        screen.fetch_screen(host)


@pytest.fixture
def window():
    app = W.QApplication.instance() or W.QApplication([])
    configure_application(app)
    widget = MainWindow()
    x = np.linspace(0, .001, 101)
    widget.set_traces([Trace("CH1", x, np.sin(x*10000))], "analysis")
    widget.show()
    app.processEvents()
    yield widget
    widget.set_screen_auto(False)
    widget.set_live(False)
    widget.instrument_panel.invalidate()
    widget.dirty = False
    widget.close()


def test_image_mode_preserves_math_samples_zoom_and_dirty_state(window, png):
    window.expression.setText("CH1 * 2")
    window.add_expression()
    window.plot.setRange(xRange=(.0002, .0007), yRange=(-.5, .5), padding=0)
    window.cursor_a.setValue(.0003)
    traces, curves = window.traces, window.curves[:]
    ranges = np.array(window.plot.viewRange())
    values = [t.y.copy() for t in traces]
    assert window.dirty
    window.mode_tabs.setCurrentIndex(1)
    window.network_result("SCREEN", "scope", dict(generation=window._screen_generation, png=png, seconds=7.3))
    assert window.traces is traces and window.curves == curves and window.dirty
    for trace, expected in zip(window.traces, values):
        np.testing.assert_array_equal(trace.y, expected)
    np.testing.assert_allclose(window.plot.viewRange(), ranges)
    assert window.cursor_a.value() == .0003
    assert window.screen_panel.png == png and window.screen_panel.frames == 1
    assert not window.file_actions["CSV出力"].isEnabled()
    window.mode_tabs.setCurrentIndex(0)
    assert window.file_actions["CSV出力"].isEnabled()
    np.testing.assert_allclose(window.plot.viewRange(), ranges)


def test_screen_auto_and_waveform_live_are_mutually_exclusive(window):
    window.set_live(True)
    window._live_timer.stop()
    window.set_screen_auto(True)
    assert not window.live_enabled and not window._live_timer.isActive()
    assert window.screen_enabled and window.mode_tabs.currentIndex() == 1
    window.set_live(True)
    window._live_timer.stop()
    assert not window.screen_enabled and not window._screen_timer.isActive()
    assert window.live_enabled and window.mode_tabs.currentIndex() == 0


def test_old_screen_cannot_update_after_connection_or_mode_change(window, png):
    window.mode_tabs.setCurrentIndex(1)
    previous = dict(generation=window._screen_generation, png=png, seconds=1)
    window.host.setText("another-scope")
    window.network_result("SCREEN", "old-scope", previous)
    assert window.screen_panel.png is None
    previous["generation"] = window._screen_generation
    window.mode_tabs.setCurrentIndex(0)
    window.network_result("SCREEN", "another-scope", previous)
    assert window.screen_panel.png is None


def test_screen_worker_never_opens_control_connection(window, monkeypatch, png):
    import yokogawa_tool.gui.app as module
    calls = []
    def forbidden_control(**config):
        pytest.fail("Screen display must not open the TCP control protocol")
    def fetch(host, **config):
        calls.append((host, config))
        return {"png": png, "seconds": .1}
    monkeypatch.setattr(module, "DL1640", forbidden_control)
    monkeypatch.setattr(module, "fetch_screen", fetch)
    window.read_screen()
    for _ in range(100):
        QtTest.QTest.qWait(10)
        if window.worker is None:
            break
    assert len(calls) == 1 and window.screen_panel.png == png
    assert not window.dirty and window.worker is None


def test_leaving_screen_mode_while_worker_runs_discards_late_image(window, monkeypatch, png):
    import threading
    import yokogawa_tool.gui.app as module
    entered, release = threading.Event(), threading.Event()
    traces = window.traces
    def fetch(host, **config):
        entered.set()
        assert release.wait(2)
        return {"png": png, "seconds": .2}
    monkeypatch.setattr(module, "fetch_screen", fetch)
    window.read_screen()
    try:
        assert entered.wait(1)
        window.mode_tabs.setCurrentIndex(0)
        assert "停止" in window.screen_panel.status.text()
    finally:
        release.set()
        for _ in range(100):
            QtTest.QTest.qWait(10)
            if window.worker is None:
                break
    assert window.worker is None and window.screen_panel.png is None
    assert window.traces is traces and not window.dirty


def test_screen_failure_keeps_analysis_settings_and_stops_auto(window):
    from test_panel_sync import DATA
    window.instrument_panel.update_settings(DATA)
    window.set_screen_auto(True)
    window._screen_timer.stop()
    window.network_failed("HTTP timeout", "SCREEN", window._screen_generation)
    assert not window.screen_enabled and window.instrument_panel._loaded
    assert "HTTP timeout" in window.screen_panel.status.text()
    assert len(window.traces) == 1 and not window.dirty


def test_screen_image_save_uses_original_png(window, png, tmp_path, monkeypatch):
    window.mode_tabs.setCurrentIndex(1)
    window.screen_panel.set_frame(png, "scope", 1)
    path = tmp_path / "screen.png"
    monkeypatch.setattr(W.QFileDialog, "getSaveFileName", lambda *args: (str(path), "PNG (*.png)"))
    window.screen_panel.view.scale(2, 2)
    window.image_dialog()
    assert path.read_bytes() == png and len(window.traces) == 1
    assert not window.dirty
