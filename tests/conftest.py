"""Unit and GUI tests must never connect to a real oscilloscope."""
import socket
import pytest


@pytest.fixture(autouse=True)
def block_real_connections():
    # Transport tests install their own fake connection after this fixture.
    # GUI timers can otherwise initiate automatic reads during event handling.
    def forbidden(address, *args, **kwargs):
        raise OSError(f'Real network access is disabled during tests: {address}')
    # Use a private context: sharing the monkeypatch fixture would change its
    # teardown order relative to GUI fixtures and keep test-specific mocks alive
    # while windows close.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket, 'create_connection', forbidden)
        yield
