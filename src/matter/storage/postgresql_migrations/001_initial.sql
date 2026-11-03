-- Matter PostgreSQL schema 1. Exact UTF-8 bytes identify this migration.
-- The backend supplies a private, validated schema in search_path and one
-- enclosing transaction. Canonical JSON is BYTEA, never database-rendered JSON.

CREATE TABLE schema_migrations (
    version integer PRIMARY KEY CHECK (version >= 1),
    name text NOT NULL UNIQUE,
    checksum text NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
    applied_at text NOT NULL
);

-- UTF-8 conversion is stable under the required UTF8 server encoding. Keep
-- complete opaque identifiers out of btree tuples: the portable contract has
-- no small length limit. Exact text is retained and compared on every lookup;
-- a digest collision can cause refusal, never substitute another identity.
CREATE FUNCTION identity_key(text) RETURNS bytea
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE SET search_path = pg_catalog AS $$
    SELECT sha256(convert_to($1, 'UTF8'));
$$;

CREATE TABLE commands (
    scope_id text COLLATE "C" NOT NULL,
    scope_key bytea GENERATED ALWAYS AS (identity_key(scope_id)) STORED NOT NULL,
    idempotency_key text COLLATE "C" NOT NULL,
    idempotency_hash bytea GENERATED ALWAYS AS (identity_key(idempotency_key)) STORED NOT NULL,
    command_id text COLLATE "C" NOT NULL,
    command_key bytea GENERATED ALWAYS AS (identity_key(command_id)) STORED NOT NULL,
    digest text NOT NULL CHECK (digest ~ '^[0-9a-f]{64}$'),
    command_json bytea NOT NULL,
    result_json bytea NOT NULL,
    receipt_namespace text COLLATE "C" NOT NULL,
    receipt_namespace_key bytea GENERATED ALWAYS AS (identity_key(receipt_namespace)) STORED NOT NULL,
    receipt_id text COLLATE "C" NOT NULL,
    receipt_id_key bytea GENERATED ALWAYS AS (identity_key(receipt_id)) STORED NOT NULL,
    receipt_version bigint NOT NULL DEFAULT 1 CHECK (receipt_version = 1),
    PRIMARY KEY (scope_key, idempotency_hash),
    UNIQUE (scope_key, command_key),
    UNIQUE (scope_key, receipt_namespace_key, receipt_id_key)
);

CREATE TABLE versions (
    scope_id text COLLATE "C" NOT NULL,
    scope_key bytea GENERATED ALWAYS AS (identity_key(scope_id)) STORED NOT NULL,
    namespace text COLLATE "C" NOT NULL,
    namespace_key bytea GENERATED ALWAYS AS (identity_key(namespace)) STORED NOT NULL,
    id text COLLATE "C" NOT NULL,
    id_key bytea GENERATED ALWAYS AS (identity_key(id)) STORED NOT NULL,
    record_type text COLLATE "C" NOT NULL,
    version bigint NOT NULL CHECK (version BETWEEN 1 AND 9007199254740991),
    digest text NOT NULL CHECK (digest ~ '^[0-9a-f]{64}$'),
    content bytea NOT NULL,
    command_id text COLLATE "C" NOT NULL,
    command_key bytea GENERATED ALWAYS AS (identity_key(command_id)) STORED NOT NULL,
    PRIMARY KEY (scope_key, namespace_key, id_key, version),
    UNIQUE (scope_key, namespace_key, id_key, digest),
    FOREIGN KEY (scope_key, command_key) REFERENCES commands (scope_key, command_key)
        DEFERRABLE INITIALLY DEFERRED
);

ALTER TABLE commands ADD CONSTRAINT commands_receipt_fkey
    FOREIGN KEY (scope_key, receipt_namespace_key, receipt_id_key, receipt_version)
    REFERENCES versions (scope_key, namespace_key, id_key, version)
    DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX versions_by_command ON versions (scope_key, command_key);

CREATE TABLE heads (
    scope_id text COLLATE "C" NOT NULL,
    scope_key bytea GENERATED ALWAYS AS (identity_key(scope_id)) STORED NOT NULL,
    namespace text COLLATE "C" NOT NULL,
    namespace_key bytea GENERATED ALWAYS AS (identity_key(namespace)) STORED NOT NULL,
    id text COLLATE "C" NOT NULL,
    id_key bytea GENERATED ALWAYS AS (identity_key(id)) STORED NOT NULL,
    record_type text COLLATE "C" NOT NULL,
    version bigint NOT NULL CHECK (version BETWEEN 1 AND 9007199254740991),
    PRIMARY KEY (scope_key, namespace_key, id_key),
    FOREIGN KEY (scope_key, namespace_key, id_key, version)
        REFERENCES versions (scope_key, namespace_key, id_key, version)
);

CREATE TABLE watches (
    scope_id text COLLATE "C" NOT NULL,
    scope_key bytea GENERATED ALWAYS AS (identity_key(scope_id)) STORED NOT NULL,
    watch_key text COLLATE "C" NOT NULL,
    watch_hash bytea GENERATED ALWAYS AS (identity_key(watch_key)) STORED NOT NULL,
    namespace text COLLATE "C" NOT NULL,
    namespace_key bytea GENERATED ALWAYS AS (identity_key(namespace)) STORED NOT NULL,
    id text COLLATE "C" NOT NULL,
    id_key bytea GENERATED ALWAYS AS (identity_key(id)) STORED NOT NULL,
    PRIMARY KEY (scope_key, watch_hash, namespace_key, id_key),
    FOREIGN KEY (scope_key, namespace_key, id_key) REFERENCES heads (scope_key, namespace_key, id_key)
);

CREATE INDEX watches_by_identity ON watches (scope_key, namespace_key, id_key);

CREATE FUNCTION refuse_history_change() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    RAISE EXCEPTION 'Matter history is append-only.' USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER commands_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON commands
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_history_change();
CREATE TRIGGER versions_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON versions
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_history_change();

CREATE FUNCTION check_version_identity() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    previous_version bigint;
    previous_type text;
BEGIN
    SELECT version, record_type INTO previous_version, previous_type FROM versions
        WHERE scope_key = identity_key(NEW.scope_id)
        AND namespace_key = identity_key(NEW.namespace) AND id_key = identity_key(NEW.id)
        AND scope_id = NEW.scope_id AND namespace = NEW.namespace AND id = NEW.id
        ORDER BY version DESC LIMIT 1;
    IF NEW.version <> coalesce(previous_version + 1, 1) THEN
        RAISE EXCEPTION 'Matter versions must be consecutive.' USING ERRCODE = '23514';
    END IF;
    IF previous_type IS NOT NULL AND previous_type <> NEW.record_type THEN
        RAISE EXCEPTION 'Matter identity cannot change type.' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER versions_identity BEFORE INSERT ON versions
    FOR EACH ROW EXECUTE FUNCTION check_version_identity();

CREATE FUNCTION check_head_identity() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM versions WHERE scope_key = identity_key(NEW.scope_id)
        AND namespace_key = identity_key(NEW.namespace) AND id_key = identity_key(NEW.id)
        AND scope_id = NEW.scope_id
        AND namespace = NEW.namespace AND id = NEW.id AND version = NEW.version
        AND record_type <> NEW.record_type) THEN
        RAISE EXCEPTION 'Matter head must retain version type.' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER heads_identity BEFORE INSERT OR UPDATE ON heads
    FOR EACH ROW EXECUTE FUNCTION check_head_identity();
