"""Synthetic HOST adapter for conformance, never a StateCivics implementation.

Packet lookup is explicitly mapped from a scoped payload digest to packet_hash.
Identity hashes and reconstructed payload hashes have different meanings.
The host owns these tables and their access policy. They are not Matter schema.
"""
from matter.canonical import canonical_bytes, loads, source_digest
from matter.payloads import PayloadRead
from matter.storage import StorageError
from matter.storage.base import _validate_fragment


class HostPayloadFixture:
    def __init__(self, factory, schema, scope_id, *, allow=True, fault=None):
        self.factory, self.schema, self.scope_id = factory, schema, scope_id
        self.allow, self.fault = allow, fault

    @staticmethod
    def initialize(factory, schema):
        from psycopg import sql
        with factory() as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            conn.execute(sql.SQL("CREATE TABLE {}.packets (scope_id text, packet_hash text, "
                                "evidence_hash text NOT NULL, exact_material bytea NOT NULL, "
                                "PRIMARY KEY(scope_id,packet_hash))").format(sql.Identifier(schema)))
            conn.execute(sql.SQL("CREATE TABLE {}.payload_refs (scope_id text, digest text, packet_hash text, "
                                "body bytea, PRIMARY KEY(scope_id,digest), "
                                "CHECK ((packet_hash IS NULL) <> (body IS NULL)))").format(sql.Identifier(schema)))

    def _query(self, text):
        from psycopg import sql
        return sql.SQL(text).format(sql.Identifier(self.schema))

    def register_packet(self, packet_hash, identity, material):
        data = canonical_bytes(material)
        digest = source_digest(data)
        with self.factory() as conn:
            conn.execute(self._query("INSERT INTO {}.packets VALUES (%s,%s,%s,%s)"),
                         (self.scope_id, packet_hash, source_digest(canonical_bytes(identity)), data))
            conn.execute(self._query("INSERT INTO {}.payload_refs VALUES (%s,%s,%s,NULL) ON CONFLICT DO NOTHING"),
                         (self.scope_id, digest, packet_hash))
        return data, digest

    def _read(self, conn, digest):
        row = conn.execute(self._query("SELECT packet_hash,body FROM {}.payload_refs WHERE scope_id=%s AND digest=%s"),
                           (self.scope_id, digest)).fetchone()
        if row is None:
            return None
        packet_hash, body = row
        if packet_hash is not None:
            # The stored identity hash is deliberately not selected or trusted
            # as a payload hash. Canonicalize exact_material on every read.
            packet = conn.execute(self._query("SELECT exact_material FROM {}.packets WHERE scope_id=%s AND packet_hash=%s"),
                                  (self.scope_id, packet_hash)).fetchone()
            if packet is None:
                return None
            body = canonical_bytes(loads(packet[0]))
        if source_digest(body) != digest:
            raise StorageError("E_EVIDENCE_INVALID")
        return body

    def put(self, data):
        if type(data) is not bytes:
            raise StorageError("E_SCHEMA_INVALID")
        digest = source_digest(data)
        with self.factory() as conn:
            conn.execute(self._query("INSERT INTO {}.payload_refs VALUES (%s,%s,NULL,%s) ON CONFLICT DO NOTHING"),
                         (self.scope_id, digest, data))
            if self._read(conn, digest) != data:
                raise StorageError("E_EVIDENCE_INVALID")
            if self.fault:
                self.fault("before_commit")
        if self.fault:
            self.fault("after_commit")
        return digest

    def read(self, content):
        ref = _validate_fragment(content, "source_content")
        availability = ref["availability"]
        if availability["status"] != "available":
            return PayloadRead(availability["status"], ref["digest"], None, availability["reason"])
        if not self.allow:
            return PayloadRead("withheld", ref["digest"], None, "Synthetic current host denial.")
        with self.factory() as conn:
            data = self._read(conn, ref["digest"])
        if data is None:
            return PayloadRead("unavailable", ref["digest"], None, "Missing scoped host artifact.")
        if "byte_length" in ref and len(data) != ref["byte_length"]:
            raise StorageError("E_EVIDENCE_INVALID")
        return PayloadRead("available", ref["digest"], data, None)
