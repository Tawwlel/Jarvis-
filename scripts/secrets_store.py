"""
Where API keys and the memory-encryption key live.

Windows (normal case): the Windows Credential Manager, via `keyring`. It is
encrypted by the OS and tied to the signed-in Windows user, and nothing secret
is ever written to config.local.json or to GitHub.

If no OS keyring exists (some Linux setups) a local file is used instead, encrypted
with a key sitting next to it. That is weaker (anyone who can read both files can
decrypt) and Jarvis says so in the log.
"""
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

SERVICE = "JarvisApricotDigital"
DATA_DIR = Path(__file__).parent.parent / "data"
PREFIX = "enc:"


class SecretStore:
    def __init__(self, data_dir: Path | None = None):
        self.dir = Path(data_dir or DATA_DIR)
        self._kr = self._try_keyring()
        self._fernet: Fernet | None = None
        self.backend = "os-keyring" if self._kr else "encrypted-file"
        if not self._kr:
            print("[secrets] no OS keyring found; using an encrypted file (weaker protection)")

    @staticmethod
    def _try_keyring():
        try:
            import keyring

            keyring.set_password(SERVICE, "_probe", "1")
            if keyring.get_password(SERVICE, "_probe") != "1":
                return None
            return keyring
        except Exception:
            return None

    # ----- file fallback -----
    def _file_fernet(self) -> Fernet:
        self.dir.mkdir(parents=True, exist_ok=True)
        kf = self.dir / ".filekey"
        if not kf.exists():
            kf.write_bytes(Fernet.generate_key())
            try:
                os.chmod(kf, 0o600)
            except OSError:
                pass
        return Fernet(kf.read_bytes())

    def _file_read(self) -> dict:
        p = self.dir / "secrets.enc"
        if not p.exists():
            return {}
        try:
            return json.loads(self._file_fernet().decrypt(p.read_bytes()))
        except (InvalidToken, ValueError):
            return {}

    def _file_write(self, d: dict):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "secrets.enc").write_bytes(self._file_fernet().encrypt(json.dumps(d).encode()))

    # ----- public API -----
    def get(self, name: str) -> str | None:
        if self._kr:
            return self._kr.get_password(SERVICE, name)
        return self._file_read().get(name)

    def set(self, name: str, value: str):
        if self._kr:
            self._kr.set_password(SERVICE, name, value)
        else:
            d = self._file_read()
            d[name] = value
            self._file_write(d)

    def delete(self, name: str):
        if self._kr:
            try:
                self._kr.delete_password(SERVICE, name)
            except Exception:
                pass
        else:
            d = self._file_read()
            d.pop(name, None)
            self._file_write(d)

    def has(self, name: str) -> bool:
        return bool(self.get(name))

    # ----- encryption of local data (memory database) -----
    def data_fernet(self) -> Fernet:
        if self._fernet is None:
            key = self.get("_memory_key")
            if not key:
                key = Fernet.generate_key().decode()
                self.set("_memory_key", key)
            self._fernet = Fernet(key.encode())
        return self._fernet


_default: SecretStore | None = None


def default_store() -> SecretStore:
    global _default
    if _default is None:
        _default = SecretStore()
    return _default


def set_default_store(store: SecretStore | None):
    global _default
    _default = store


def encrypt_text(s: str) -> str:
    return PREFIX + default_store().data_fernet().encrypt(s.encode()).decode()


def decrypt_text(s):
    """Decrypts values written by encrypt_text; rows saved before encryption pass through."""
    if not isinstance(s, str) or not s.startswith(PREFIX):
        return s
    try:
        return default_store().data_fernet().decrypt(s[len(PREFIX):].encode()).decode()
    except InvalidToken:
        return "(unreadable: encrypted with a different key)"
