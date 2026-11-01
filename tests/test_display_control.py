import pytest
from test_instrument_settings import SettingsScope


class Socket:
    closed = False
    def close(self):
        self.closed = True


@pytest.mark.parametrize('initial', ['0', '1'])
def test_lcd_restores_original_state_on_close(initial):
    scope = SettingsScope()
    scope.responses[':SYSTEM:LCD:MODE?'] = initial
    socket = scope.socket = Socket()
    scope.set_display_blanked(True)
    scope.set_display_blanked(True)
    assert scope.commands.count(':SYSTEM:LCD:MODE OFF') == int(initial)
    scope.close()
    assert socket.closed and scope.socket is None
    assert scope.commands[-1] == ':SYSTEM:LCD:MODE ' + ('ON' if initial == '1' else 'OFF')
    assert not any(c in (':START', ':STOP') for c in scope.commands)


def test_unchecking_preference_restores_without_waiting_for_close():
    scope = SettingsScope()
    scope.responses[':SYSTEM:LCD:MODE?'] = '1'
    scope.set_display_blanked(True)
    scope.set_display_blanked(False)
    assert scope.commands == [':SYSTEM:LCD:MODE OFF', ':SYSTEM:LCD:MODE ON']
    scope.restore_display()
    assert len(scope.commands) == 2


def test_restore_failure_closes_socket_and_reports_actual_problem(caplog):
    scope = SettingsScope()
    scope.responses[':SYSTEM:LCD:MODE?'] = '1'
    socket = scope.socket = Socket()
    scope.set_display_blanked(True)
    def fail(command):
        raise OSError('disconnected')
    scope.write = fail
    original_timeout = scope.timeout
    scope.close()
    assert socket.closed and scope.socket is None
    assert scope.timeout == original_timeout
    assert 'LCD' in scope.display_restore_error and 'disconnected' in caplog.text


def test_manual_lcd_controls_validate_and_do_not_change_acquisition():
    scope = SettingsScope()
    scope.responses.update({':SYSTEM:LCD:MODE?': '1', ':SYSTEM:LCD:BRIGHTNESS?': '4'})
    scope.configure_lcd(enabled=False, brightness=4)
    assert scope.commands == [':SYSTEM:LCD:MODE OFF', ':SYSTEM:LCD:BRIGHTNESS 4']
    assert scope._original_display is None
    with pytest.raises(ValueError):
        scope.configure_lcd(enabled=True, brightness=5)
    assert len(scope.commands) == 2
