CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS instances (
    id UUID PRIMARY KEY,
    name TEXT NULL,
    cpu INT NOT NULL,
    memory_mib INT NOT NULL,
    disk_gib INT NOT NULL,
    status TEXT NOT NULL,
    ip_address INET NULL,
    host_node TEXT NOT NULL,
    reserve_resources BOOLEAN NOT NULL DEFAULT true,
    last_task_id UUID NULL,
    deleted_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE instances ADD COLUMN IF NOT EXISTS reserve_resources BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE instances ADD COLUMN IF NOT EXISTS last_task_id UUID NULL;
ALTER TABLE instances ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'instances_status_check'
    ) THEN
        ALTER TABLE instances DROP CONSTRAINT instances_status_check;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'instances_status_check_async'
    ) THEN
        ALTER TABLE instances
            ADD CONSTRAINT instances_status_check_async
            CHECK (status IN (
                'creating_pending',
                'updating_pending',
                'deleting_pending',
                'running',
                'stopped',
                'error',
                'deleted'
            ));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS resource_capacity (
    host_node TEXT PRIMARY KEY,
    total_cpu INT NOT NULL,
    total_memory_mib INT NOT NULL,
    total_disk_gib INT NOT NULL
);

CREATE TABLE IF NOT EXISTS instance_tasks (
    id UUID PRIMARY KEY,
    instance_id UUID NOT NULL REFERENCES instances (id),
    command TEXT NOT NULL CHECK (command IN ('create', 'update', 'delete')),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    request_id UUID NOT NULL UNIQUE,
    request_payload JSONB NOT NULL,
    result_payload JSONB NULL,
    error_code TEXT NULL,
    error_message TEXT NULL,
    attempt_count INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 3,
    created_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS instance_tasks_instance_id_idx ON instance_tasks (instance_id);
CREATE INDEX IF NOT EXISTS instance_tasks_status_idx ON instance_tasks (status);

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'operator', 'viewer')),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS users_role_idx ON users (role);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS refresh_tokens_user_id_idx ON refresh_tokens (user_id);
CREATE INDEX IF NOT EXISTS refresh_tokens_expires_at_idx ON refresh_tokens (expires_at);

CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY,
    actor_user_id UUID NULL REFERENCES users (id) ON DELETE SET NULL,
    actor_username TEXT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NULL,
    request_id UUID NULL,
    ip_address INET NULL,
    user_agent TEXT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS audit_logs_created_at_idx ON audit_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS audit_logs_actor_user_id_idx ON audit_logs (actor_user_id);
CREATE INDEX IF NOT EXISTS audit_logs_action_idx ON audit_logs (action);
CREATE INDEX IF NOT EXISTS audit_logs_target_type_idx ON audit_logs (target_type);
CREATE INDEX IF NOT EXISTS audit_logs_request_id_idx ON audit_logs (request_id);

CREATE OR REPLACE VIEW resource_reservations_view AS
SELECT
    host_node,
    COALESCE(SUM(cpu), 0) AS reserved_cpu,
    COALESCE(SUM(memory_mib), 0) AS reserved_memory_mib,
    COALESCE(SUM(disk_gib), 0) AS reserved_disk_gib
FROM instances
WHERE reserve_resources = true
  AND status <> 'deleted'
GROUP BY host_node;
