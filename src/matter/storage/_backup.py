"""Verified SQLite snapshot copies to a new destination, without replacement.

The source is opened read-only. A stable read transaction spans source
verification and SQLite's online backup so a copied command journal and its
records describe one committed snapshot. Publication uses an atomic hard link:
an existing path, including a broken symlink, can never be overwritten.

The deadline bounds SQLite progress and lock waiting. It cannot interrupt a
filesystem syscall that is already blocked in the operating system. If final
directory synchronization fails after publication, a complete new destination
may remain; the helper never removes a published path that another process
could have replaced in the meantime.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
import sqlite3
import tempfile
from time import monotonic

from .base import StorageError
from .migrations import check_database


_STAGING_PREFIX = ".matter-backup-"
_COPY_PAGES = 128


class _CopyTimedOut(Exception):
    """Internal sentinel; no source paths or SQLite details are exposed."""


class _Deadline:
    def __init__(self, timeout: float) -> None:
        self.ends_at = monotonic() + timeout

    def check(self) -> None:
        if monotonic() >= self.ends_at:
            raise _CopyTimedOut

    def remaining(self) -> float:
        self.check()
        return max(0.0, self.ends_at - monotonic())

    def sql_progress(self) -> int:
        return int(monotonic() >= self.ends_at)

    def backup_progress(self, status: int, remaining: int, total: int) -> None:
        del status, remaining, total
        self.check()


def _verify_database(db: sqlite3.Connection, deadline: _Deadline) -> None:
    deadline.check()
    check_database(db)
    deadline.check()
    rows = db.execute("PRAGMA integrity_check").fetchall()
    if len(rows) != 1 or tuple(rows[0]) != ("ok",):
        raise StorageError(
            "E_STORAGE_UNAVAILABLE", "Database integrity verification failed."
        )
    deadline.check()
    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise StorageError(
            "E_STORAGE_UNAVAILABLE", "Database reference verification failed."
        )
    deadline.check()


def _configure_target(db: sqlite3.Connection, deadline: _Deadline) -> None:
    deadline.check()
    mode = db.execute("PRAGMA journal_mode=DELETE").fetchone()
    db.execute("PRAGMA synchronous=EXTRA")
    synchronous = db.execute("PRAGMA synchronous").fetchone()
    db.execute("PRAGMA foreign_keys=ON")
    foreign_keys = db.execute("PRAGMA foreign_keys").fetchone()
    if (
        mode is None or mode[0] != "delete"
        or synchronous is None or synchronous[0] != 3
        or foreign_keys is None or foreign_keys[0] != 1
    ):
        raise StorageError(
            "E_STORAGE_UNAVAILABLE", "Database copy durability settings are unavailable."
        )
    deadline.check()


def _table_counts(db: sqlite3.Connection, deadline: _Deadline) -> dict[str, int]:
    """Check that every trusted application table survives the snapshot copy."""
    deadline.check()
    names = db.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT GLOB 'sqlite_*' ORDER BY name"
    ).fetchall()
    result = {}
    for row in names:
        deadline.check()
        # check_database has already admitted the complete trusted schema.
        # Quoting remains necessary even for identifiers obtained from SQLite.
        name = row[0]
        quoted = '"' + name.replace('"', '""') + '"'
        result[name] = db.execute("SELECT count(*) FROM " + quoted).fetchone()[0]
    deadline.check()
    return result


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    # Windows does not expose a portable directory handle suitable for fsync.
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_staging(path: Path | None) -> None:
    if path is None:
        return
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            Path(str(path) + suffix).unlink(missing_ok=True)
        except OSError:
            # Cleanup cannot justify deleting an unrelated destination or
            # masking the primary safe failure with a raw filesystem error.
            pass


def copy_database(
    source: Path, destination: Path, *, timeout: float = 5.0,
) -> Path:
    """Publish a verified snapshot at a NEW path and return that absolute path.

    Both paths must refer to files in existing parent directories. No directory
    is created and no existing destination is replaced. Source access, backup,
    integrity checks, and target verification are read/copy operations only.
    Restore uses this same operation to create a new database; it does not edit
    a live database. A failed attempt removes its staging files where possible.
    """
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise StorageError("E_SCHEMA_INVALID", "The database copy timeout is invalid.")
    try:
        duration = float(timeout)
    except (OverflowError, ValueError):
        raise StorageError(
            "E_SCHEMA_INVALID", "The database copy timeout is invalid."
        ) from None
    if not math.isfinite(duration) or duration <= 0:
        raise StorageError("E_SCHEMA_INVALID", "The database copy timeout is invalid.")
    if not isinstance(source, Path) or not isinstance(destination, Path):
        raise StorageError("E_SCHEMA_INVALID", "Database copy paths must be Path values.")

    deadline = _Deadline(duration)
    source_db = None
    target_db = None
    staging = None
    try:
        try:
            source_path = source.resolve(strict=True)
            destination_path = destination.parent.resolve(strict=True) / destination.name
        except RuntimeError:
            # Some supported pathlib versions report a symlink cycle with a
            # RuntimeError whose text contains a filesystem path.
            raise StorageError(
                "E_STORAGE_UNAVAILABLE", "The database copy path is unavailable."
            ) from None
        if not source_path.is_file():
            raise StorageError("E_STORAGE_UNAVAILABLE", "The source database is unavailable.")
        if os.path.lexists(destination_path):
            raise StorageError(
                "E_STORAGE_UNAVAILABLE", "A database copy requires a new destination."
            )
        deadline.check()
        source_db = sqlite3.connect(
            source_path.as_uri() + "?mode=ro", uri=True,
            timeout=min(5.0, deadline.remaining()), isolation_level=None,
        )
        source_db.set_progress_handler(deadline.sql_progress, 1000)
        source_db.execute("PRAGMA query_only=ON")
        source_db.execute("BEGIN")
        _verify_database(source_db, deadline)
        source_counts = _table_counts(source_db, deadline)

        descriptor, staging_name = tempfile.mkstemp(
            prefix=_STAGING_PREFIX, suffix=".sqlite3", dir=destination_path.parent,
        )
        staging = Path(staging_name)
        os.close(descriptor)
        target_db = sqlite3.connect(
            staging, timeout=min(5.0, deadline.remaining()), isolation_level=None,
        )
        target_db.set_progress_handler(deadline.sql_progress, 1000)
        _configure_target(target_db, deadline)
        source_db.backup(
            target_db, pages=_COPY_PAGES, progress=deadline.backup_progress,
            sleep=min(0.05, deadline.remaining()),
        )
        deadline.check()
        # Verify again after copying: the source's header must not loosen the
        # destination's required rollback-journal and synchronization settings.
        _configure_target(target_db, deadline)
        _verify_database(target_db, deadline)
        if _table_counts(target_db, deadline) != source_counts:
            raise StorageError(
                "E_STORAGE_UNAVAILABLE", "Database copy completeness verification failed."
            )

        source_db.close()
        source_db = None
        target_db.close()
        target_db = None
        deadline.check()
        _fsync_file(staging)
        deadline.check()
        # os.link fails atomically if any destination entry already exists.
        # Do not replace this with rename/replace, which can overwrite a live DB.
        os.link(staging, destination_path)
        staging.unlink()
        _fsync_directory(destination_path.parent)
        return destination_path
    except StorageError:
        raise
    except _CopyTimedOut:
        raise StorageError(
            "E_STORAGE_UNAVAILABLE", "Database copy exceeded its allowed time.",
            retriable=True,
        ) from None
    except (OSError, sqlite3.Error, ValueError, OverflowError):
        if monotonic() >= deadline.ends_at:
            raise StorageError(
                "E_STORAGE_UNAVAILABLE", "Database copy exceeded its allowed time.",
                retriable=True,
            ) from None
        raise StorageError(
            "E_STORAGE_UNAVAILABLE", "The database copy could not be completed safely.",
            retriable=True,
        ) from None
    finally:
        for db in (target_db, source_db):
            if db is not None:
                try:
                    db.close()
                except sqlite3.Error:
                    pass
        _remove_staging(staging)
