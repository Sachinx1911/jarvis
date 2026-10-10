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
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    yield tmp_path
    keyring.set_keyring(previous)
