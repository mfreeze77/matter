"""Scoped storage for immutable, exact original-source bytes.

Payload publication is outside the SQLite transaction. Ingestion publishes and
synchronizes a blob before committing its reference; a failed command can leave
an unreferenced blob, but cannot roll back or overwrite other evidence. Such
orphans are harmless to observation identity. Garbage collection is out of scope.
Back up this store independently of the SQLite database; restored metadata may
explicitly report missing bytes until its matching payloads are also restored.

The host controls the root directory and filesystem permissions. Scope hashes
prevent opaque IDs from becoming path components; they are not authentication
or encryption. Locator URIs and selectors remain evidence metadata and are never
followed here. New directories are private and files are published without
replacement, using a staged file and atomic hard link on the same filesystem.

Successful puts synchronize file data and directory entries. As with SQLite
backup, Python on Windows does not expose portable directory fsync; that part
of the durability guarantee is limited to operating systems which support it.
A failure after publication can leave a complete blob while returning a storage
error. Retrying verifies and synchronizes that same blob rather than replacing
it. Process-crash tests do not establish physical power-loss qualification.
"""

from __future__ import annotations

from dataclasses import dataclass
import errno
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Literal, Protocol

from .canonical import canonical_digest, source_digest
from .storage.base import StorageError, _validate_fragment


__all__ = ["PayloadRead", "PayloadStore", "FilePayloadStore"]


@dataclass(frozen=True, slots=True)
class PayloadRead:
    """Availability of one exact content digest in the authorized scope."""

    status: Literal["available", "unavailable", "withheld"]
    digest: str
    data: bytes | None
    reason: str | None


class PayloadStore(Protocol):
    """Host-authorized, scope-bound original-byte storage."""

    @property
    def scope_id(self) -> str: ...

    def put(self, data: bytes) -> str:
        """Durably publish exact bytes and return their unframed SHA-256 digest."""
        ...

    def read(self, content: dict[str, Any]) -> PayloadRead:
        """Respect declared availability, then verify locally stored bytes."""
        ...


def _storage_error() -> StorageError:
    return StorageError(
        "E_STORAGE_UNAVAILABLE", "The scoped payload store could not be accessed safely.",
        retriable=True,
    )


def _invalid_evidence() -> StorageError:
    return StorageError(
        "E_EVIDENCE_INVALID", "Stored payload bytes do not match their content reference."
    )


def _fsync_directory(path: Path) -> None:
    # Python's Windows API lacks a portable fsync-capable directory handle.
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class FilePayloadStore:
    """A local content-addressed directory, separated by a versioned scope hash.

    ``path`` is a host-selected root whose parent must already exist. The root
    and scope directory are created lazily on the first put, with mode 0700;
    existing directory permissions are not changed. Metadata-only unavailable
    or withheld reads do not access the payload filesystem. Each published blob
    has the permissions of its private mode-0600 staging file.
    """

    __slots__ = ("_scope_id", "_root", "_directory")

    def __init__(self, path: str | Path, *, scope_id: str) -> None:
        self._scope_id = _validate_fragment(scope_id, "identifier")
        if not isinstance(path, (str, Path)) or not str(path) or "\x00" in str(path):
            raise StorageError("E_SCHEMA_INVALID", "A filesystem payload directory is required.")
        try:
            self._root = Path(path).absolute()
        except (OSError, ValueError):
            raise _storage_error() from None
        scope_key = canonical_digest(self._scope_id, "payload-scope.v1")
        self._directory = self._root / scope_key

    @property
    def scope_id(self) -> str:
        return self._scope_id

    def _scope_exists(self) -> bool:
        try:
            metadata = self._directory.lstat()
        except FileNotFoundError:
            return False
        # A scope directory cannot alias another scope through a symlink.
        if not stat.S_ISDIR(metadata.st_mode):
            raise _storage_error()
        return True

    def _prepare_directories(self) -> None:
        self._root.mkdir(mode=0o700, exist_ok=True)
        self._directory.mkdir(mode=0o700, exist_ok=True)
        if not self._scope_exists():
            raise _storage_error()
        # Repeat these on retries: an earlier attempt may have failed while
        # confirming durability of a newly created directory's name.
        _fsync_directory(self._root)
        _fsync_directory(self._root.parent)

    def _read_blob(
        self, digest: str, byte_length: int | None = None, *, synchronize: bool = False,
    ) -> bytes | None:
        if not self._scope_exists():
            return None
        path = self._directory / digest
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(metadata.st_mode):
            raise _invalid_evidence()
        # O_NOFOLLOW guards the final component where supported. O_NONBLOCK
        # prevents a replaced FIFO from blocking before its type is checked.
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            return None
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise _invalid_evidence() from None
            raise
        try:
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1  # The file object now owns the descriptor.
                opened = os.fstat(handle.fileno())
                if not stat.S_ISREG(opened.st_mode):
                    raise _invalid_evidence()
                if byte_length is not None and opened.st_size != byte_length:
                    raise _invalid_evidence()
                data = handle.read()
                if source_digest(data) != digest:
                    raise _invalid_evidence()
                if byte_length is not None and len(data) != byte_length:
                    raise _invalid_evidence()
                if synchronize:
                    os.fsync(handle.fileno())
                return data
        finally:
            if descriptor != -1:
                os.close(descriptor)

    def put(self, data: bytes) -> str:
        """Publish once; a retry verifies existing bytes without replacing them."""
        if type(data) is not bytes:
            raise StorageError("E_SCHEMA_INVALID", "Original payload must be bytes.")
        digest = source_digest(data)
        staging: Path | None = None
        descriptor = -1
        try:
            self._prepare_directories()
            existing = self._read_blob(digest, len(data), synchronize=True)
            if existing is not None:
                # Digest verification alone is not used as a substitute for
                # exact equality when the caller already has the source bytes.
                if existing != data:
                    raise _invalid_evidence()
                _fsync_directory(self._directory)
                return digest
            descriptor, name = tempfile.mkstemp(prefix=".matter-payload-", dir=self._directory)
            staging = Path(name)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                if handle.write(data) != len(data):
                    raise _storage_error()
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(staging, self._directory / digest)
            except FileExistsError:
                # Another publisher won. Its complete bytes must agree; never
                # truncate, rename over, or otherwise repair a conflicting blob.
                existing = self._read_blob(digest, len(data), synchronize=True)
                if existing is None:
                    raise _storage_error()
                if existing != data:
                    raise _invalid_evidence()
            staging.unlink()
            staging = None
            _fsync_directory(self._directory)
            return digest
        except StorageError:
            raise
        except (OSError, ValueError):
            raise _storage_error() from None
        finally:
            if descriptor != -1:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if staging is not None:
                try:
                    staging.unlink()
                except OSError:
                    pass

    def read(self, content: dict[str, Any]) -> PayloadRead:
        """Read a validated source_content reference without following its URI."""
        reference = _validate_fragment(content, "source_content")
        digest = reference["digest"]
        declared = reference["availability"]
        if declared["status"] != "available":
            return PayloadRead(declared["status"], digest, None, declared["reason"])
        try:
            data = self._read_blob(digest, reference.get("byte_length"))
        except StorageError:
            raise
        except (OSError, ValueError):
            raise _storage_error() from None
        if data is None:
            return PayloadRead(
                "unavailable", digest, None,
                "Payload bytes are not present in this scoped store.",
            )
        return PayloadRead("available", digest, data, None)
