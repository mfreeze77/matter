-- Matter SQLite schema 1. The exact UTF-8 bytes are the migration checksum.
-- Execute complete statements individually in the enclosing migration transaction.

CREATE TABLE schema_migrations (
    version INTEGER NOT NULL PRIMARY KEY
        CHECK (typeof(version) = 'integer' AND version >= 1),
    name TEXT NOT NULL UNIQUE,
    checksum TEXT NOT NULL
        CHECK (length(checksum) = 64 AND checksum NOT GLOB '*[^0-9a-f]*'),
    applied_at TEXT NOT NULL
);

CREATE TABLE commands (
    scope_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    command_id TEXT NOT NULL,
    digest TEXT NOT NULL
        CHECK (length(digest) = 64 AND digest NOT GLOB '*[^0-9a-f]*'),
    command_json BLOB NOT NULL CHECK (typeof(command_json) = 'blob'),
    result_json BLOB NOT NULL CHECK (typeof(result_json) = 'blob'),
    receipt_namespace TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    receipt_version INTEGER NOT NULL DEFAULT 1
        CHECK (typeof(receipt_version) = 'integer' AND receipt_version = 1),
    PRIMARY KEY (scope_id, idempotency_key),
    UNIQUE (scope_id, command_id),
    UNIQUE (scope_id, receipt_namespace, receipt_id),
    FOREIGN KEY (scope_id, receipt_namespace, receipt_id, receipt_version)
        REFERENCES versions (scope_id, namespace, id, version)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE versions (
    scope_id TEXT NOT NULL,
    namespace TEXT NOT NULL,
    id TEXT NOT NULL,
    record_type TEXT NOT NULL,
    version INTEGER NOT NULL
        CHECK (typeof(version) = 'integer' AND version BETWEEN 1 AND 9007199254740991),
    digest TEXT NOT NULL
        CHECK (length(digest) = 64 AND digest NOT GLOB '*[^0-9a-f]*'),
    content BLOB NOT NULL CHECK (typeof(content) = 'blob'),
    command_id TEXT NOT NULL,
    PRIMARY KEY (scope_id, namespace, id, version),
    UNIQUE (scope_id, namespace, id, digest),
    FOREIGN KEY (scope_id, command_id)
        REFERENCES commands (scope_id, command_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX versions_by_command ON versions (scope_id, command_id);

CREATE TABLE heads (
    scope_id TEXT NOT NULL,
    namespace TEXT NOT NULL,
    id TEXT NOT NULL,
    record_type TEXT NOT NULL,
    version INTEGER NOT NULL
        CHECK (typeof(version) = 'integer' AND version BETWEEN 1 AND 9007199254740991),
    PRIMARY KEY (scope_id, namespace, id),
    FOREIGN KEY (scope_id, namespace, id, version)
        REFERENCES versions (scope_id, namespace, id, version)
);

CREATE TABLE watches (
    scope_id TEXT NOT NULL,
    watch_key TEXT NOT NULL,
    namespace TEXT NOT NULL,
    id TEXT NOT NULL,
    PRIMARY KEY (scope_id, watch_key, namespace, id),
    FOREIGN KEY (scope_id, namespace, id)
        REFERENCES heads (scope_id, namespace, id)
);

CREATE INDEX watches_by_identity ON watches (scope_id, namespace, id);

CREATE TRIGGER commands_no_update
BEFORE UPDATE ON commands
BEGIN
    SELECT RAISE(ABORT, 'Command journal entries are append-only.');
END;

CREATE TRIGGER commands_no_delete
BEFORE DELETE ON commands
BEGIN
    SELECT RAISE(ABORT, 'Command journal entries are append-only.');
END;

CREATE TRIGGER versions_no_update
BEFORE UPDATE ON versions
BEGIN
    SELECT RAISE(ABORT, 'Record versions are append-only.');
END;

CREATE TRIGGER versions_no_delete
BEFORE DELETE ON versions
BEGIN
    SELECT RAISE(ABORT, 'Record versions are append-only.');
END;

CREATE TRIGGER versions_identity_type
BEFORE INSERT ON versions
WHEN EXISTS (
    SELECT 1 FROM versions
    WHERE scope_id = NEW.scope_id AND namespace = NEW.namespace AND id = NEW.id
        AND record_type <> NEW.record_type
)
BEGIN
    SELECT RAISE(ABORT, 'A record identity cannot change type.');
END;

CREATE TRIGGER versions_in_sequence
BEFORE INSERT ON versions
WHEN NEW.version <> COALESCE((
    SELECT MAX(version) + 1 FROM versions
    WHERE scope_id = NEW.scope_id AND namespace = NEW.namespace AND id = NEW.id
), 1)
BEGIN
    SELECT RAISE(ABORT, 'Record versions must be consecutive.');
END;

CREATE TRIGGER heads_insert_type
BEFORE INSERT ON heads
WHEN EXISTS (
    SELECT 1 FROM versions
    WHERE scope_id = NEW.scope_id AND namespace = NEW.namespace AND id = NEW.id
        AND version = NEW.version AND record_type <> NEW.record_type
)
BEGIN
    SELECT RAISE(ABORT, 'A current record must retain its version type.');
END;

CREATE TRIGGER heads_update_type
BEFORE UPDATE ON heads
WHEN EXISTS (
    SELECT 1 FROM versions
    WHERE scope_id = NEW.scope_id AND namespace = NEW.namespace AND id = NEW.id
        AND version = NEW.version AND record_type <> NEW.record_type
)
BEGIN
    SELECT RAISE(ABORT, 'A current record must retain its version type.');
END;
