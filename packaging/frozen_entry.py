"""PyInstaller entry point and an offline smoke check for the frozen package."""
import sys
from pathlib import Path


def self_test():
    import json
    import os
    import shlex
    import tempfile
    import numpy as np
    from PySide6 import QtWidgets as W
    from yokogawa_tool.gui.app import MainWindow, configure_application
    from yokogawa_tool.gui.protocol_panel import ProtocolDialog
    from yokogawa_tool.core.waveform import save_session, load_session
    from yokogawa_tool.core.waveform import Trace
    from yokogawa_tool.protocols import decode
    from yokogawa_tool.protocols.endat import crc5

    app = W.QApplication([])
    configure_application(app)
    window = MainWindow()
    errors = []
    window.error = errors.append
    base = Path(sys.executable).parent
    window.open_path(base/'demo/0000.WVF')
    assert not errors and len(window.traces) == 3, errors
    window.expression.setText('CH1 - CH2')
    window.add_expression()
    assert len(window.traces) == 4
    window.show_fft()
    dialog = ProtocolDialog(window.traces, window.settings, window)
    dialog.protocol.setCurrentIndex(dialog.protocol.findData('endat'))
    assert not dialog.tool.isEnabled() and crc5([0]+[(0x123456 >> i)&1 for i in range(25)]) == 11
    with tempfile.TemporaryDirectory(prefix='yokogawa-package-check-') as temp:
        path = Path(temp)/'check.scope.npz'
        save_session(path, window.traces)
        restored, _ = load_session(path)
        assert len(restored) == len(window.traces)
        for expected, actual in zip(window.traces, restored):
            np.testing.assert_array_equal(actual.x, expected.x)
            np.testing.assert_array_equal(actual.y, expected.y)
        output = Path(temp)/'child-environment.txt'
        tool = Path(temp)/'fake-sigrok'
        tool.write_text('#!/bin/sh\nprintf "%s" "$LD_LIBRARY_PATH" > '+shlex.quote(str(output))+
                        '\nprintf "%s" \'{"traceEvents": []}\'\n')
        tool.chmod(0o755)
        parent_path = os.environ.get('LD_LIBRARY_PATH')
        result = decode('uart', {'rx': Trace('rx', [0, 1, 2], [0, 1, 0])},
                        {'rx': .5}, executable=str(tool))
        assert result == [] and output.read_text() == os.environ.get('LD_LIBRARY_PATH_ORIG', '')
        assert os.environ.get('LD_LIBRARY_PATH') == parent_path
    window.show()
    app.processEvents()
    image = window.grab()
    assert not image.isNull() and not errors, errors
    for child in window.windows:
        child.close()
    dialog.close()
    window.dirty = False
    window.close()
    print(json.dumps(dict(frozen=bool(getattr(sys, 'frozen', False)), waveforms=3,
                         math=True, fft=True, endat_ui=True, session_roundtrip=True,
                         rendering=True, external_decoder_environment=True), ensure_ascii=False))


if __name__ == '__main__':
    if sys.argv[1:] == ['--package-self-test']:
        self_test()
    else:
        from yokogawa_tool.app import main
        main()
