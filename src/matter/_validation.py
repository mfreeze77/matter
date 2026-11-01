"""Bounded successful structural checks; never cache permission or freshness.

Keys bind locally recomputed content digests, exact canonical bytes, schema
version and the actual validator instance (including its local registry).
Bundled validators are immutable for their process lifetime. Changing schemas
or format semantics requires a new validator instance. No caller-supplied row
digest is trusted and no mutable decoded object is retained or returned.
"""
from collections import OrderedDict
from hashlib import sha256
from threading import RLock

from .canonical import loads


class InvalidValue(ValueError):
    """Safe structural refusal without rejected payload text."""


class ValidationCache:
    def __init__(self, *, max_entries=2048, max_bytes=8 * 1024 * 1024):
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self._entries = OrderedDict()
        self._bytes = 0
        self._lock = RLock()

    def checked(self, encoded, validator, version):
        key = (id(validator), version, sha256(encoded).digest())
        with self._lock:
            prior = self._entries.get(key)
            hit = prior is not None and prior[0] is validator and prior[1] == encoded
            if hit:
                self._entries.move_to_end(key)
        # Decode on every call to provide a detached, strict value. Validate the
        # exact snapshot encoded by the caller, not a concurrently mutated dict.
        value = loads(encoded)
        if not hit:
            if not validator.is_valid(value):
                raise InvalidValue("The value does not satisfy its structural schema.")
            if len(encoded) <= self.max_bytes and self.max_entries > 0:
                with self._lock:
                    old = self._entries.pop(key, None)
                    if old is not None:
                        self._bytes -= len(old[1])
                    # Keep the validator alive so its identity cannot be reused.
                    self._entries[key] = (validator, encoded)
                    self._bytes += len(encoded)
                    while self._bytes > self.max_bytes or len(self._entries) > self.max_entries:
                        _, (_, evicted) = self._entries.popitem(last=False)
                        self._bytes -= len(evicted)
        return value


_SUCCESSFUL = ValidationCache()


def validated_bytes(encoded, validator, version):
    return _SUCCESSFUL.checked(encoded, validator, version)
