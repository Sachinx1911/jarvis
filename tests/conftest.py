import ipaddress
import os
import socket

import keyring
import pytest
from keyring.backend import KeyringBackend

# The real OS backend, captured before any test swaps it out (used only by live tests).
REAL_KEYRING = keyring.get_keyring()


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Every test gets its own JARVIS_HOME and an in-memory keyring.

    The real OS secret store and the real data folders are never touched.
    """
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_LOCAL_CONFIG", str(tmp_path / "no-local.yaml"))  # ignore config/local.yaml
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    yield tmp_path
    keyring.set_keyring(previous)


def _is_local(host) -> bool:
    if host in (None, "", "localhost") or str(host).startswith("/"):
        return True
    try:
        return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
    except ValueError:
        return False


def _is_ip_literal(host) -> bool:
    try:
        ipaddress.ip_address(str(host).split("%")[0])
        return True
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Offline tests never reach the internet: only loopback connections are allowed.

    Live tests (JARVIS_LIVE=1) keep real network access.
    """
    if os.environ.get("JARVIS_LIVE") == "1":
        yield
        return
    real_connect, real_create, real_gai = socket.socket.connect, socket.create_connection, socket.getaddrinfo

    def connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if not _is_local(host):
            raise OSError(f"network disabled in offline tests (tried {host})")
        return real_connect(self, address)

    def create_connection(address, *args, **kwargs):
        if not _is_local(address[0]):
            raise OSError(f"network disabled in offline tests (tried {address[0]})")
        return real_create(address, *args, **kwargs)

    def getaddrinfo(host, *args, **kwargs):
        if not (_is_local(host) or _is_ip_literal(host)):
            raise socket.gaierror(f"network disabled in offline tests (tried to resolve {host})")
        return real_gai(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield


@pytest.fixture(autouse=True)
def no_osascript(monkeypatch):
    """Offline tests never drive the real Notes app: the default osascript runner is replaced,
    and a test that reaches it fails (tests pass a FakeNotesRunner instead)."""
    from jarvis.connectors import applenotes

    reached: list[str] = []

    def blocked(argv, timeout):
        reached.append(argv[5] if len(argv) > 5 else "?")
        raise applenotes.NotesUnavailable("osascript is blocked in offline tests")

    monkeypatch.setattr(applenotes, "run_osascript", blocked)
    yield
    assert not reached, f"a test tried to run osascript against Notes: {reached}"
