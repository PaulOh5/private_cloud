CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

INSERT INTO tenants (id, key, name, is_active, created_at, updated_at)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'default',
    'Default Tenant',
    true,
    NOW(),
    NOW()
)
ON CONFLICT (key) DO UPDATE
SET
    name = EXCLUDED.name,
    updated_at = NOW();

CREATE TABLE IF NOT EXISTS tenant_quotas (
    tenant_id UUID PRIMARY KEY REFERENCES tenants (id) ON DELETE CASCADE,
    max_instances INT NOT NULL,
    max_cpu INT NOT NULL,
    max_memory_mib INT NOT NULL,
    max_disk_gib INT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS instances (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
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

ALTER TABLE instances ADD COLUMN IF NOT EXISTS tenant_id UUID NULL;
ALTER TABLE instances ADD COLUMN IF NOT EXISTS reserve_resources BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE instances ADD COLUMN IF NOT EXISTS last_task_id UUID NULL;
ALTER TABLE instances ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL;

UPDATE instances
SET tenant_id = '00000000-0000-0000-0000-000000000001'
WHERE tenant_id IS NULL;

ALTER TABLE instances
    ALTER COLUMN tenant_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'instances_tenant_id_fkey'
    ) THEN
        ALTER TABLE instances
            ADD CONSTRAINT instances_tenant_id_fkey
            FOREIGN KEY (tenant_id)
            REFERENCES tenants (id);
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'instances_status_check'
    ) THEN
        ALTER TABLE instances DROP CONSTRAINT instances_status_check;
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'instances_status_check_async'
    ) THEN
        ALTER TABLE instances DROP CONSTRAINT instances_status_check_async;
    END IF;

    ALTER TABLE instances
        ADD CONSTRAINT instances_status_check_async
        CHECK (status IN (
            'creating_pending',
            'updating_pending',
            'starting_pending',
            'stopping_pending',
            'deleting_pending',
            'running',
            'stopped',
            'error',
            'deleted'
        ));
END $$;

CREATE INDEX IF NOT EXISTS instances_tenant_id_idx ON instances (tenant_id);

CREATE TABLE IF NOT EXISTS resource_capacity (
    host_node TEXT PRIMARY KEY,
    total_cpu INT NOT NULL,
    total_memory_mib INT NOT NULL,
    total_disk_gib INT NOT NULL
);

CREATE TABLE IF NOT EXISTS instance_tasks (
    id UUID PRIMARY KEY,
    instance_id UUID NOT NULL REFERENCES instances (id),
    command TEXT NOT NULL CHECK (command IN ('create', 'update', 'delete', 'start', 'stop')),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'cancel_pending', 'succeeded', 'failed', 'canceled')),
    request_id UUID NOT NULL UNIQUE,
    request_payload JSONB NOT NULL,
    result_payload JSONB NULL,
    error_code TEXT NULL,
    error_message TEXT NULL,
    retry_of_task_id UUID NULL,
    canceled_by UUID NULL,
    cancel_reason TEXT NULL,
    attempt_count INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 3,
    created_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE instance_tasks ADD COLUMN IF NOT EXISTS retry_of_task_id UUID NULL;
ALTER TABLE instance_tasks ADD COLUMN IF NOT EXISTS canceled_by UUID NULL;
ALTER TABLE instance_tasks ADD COLUMN IF NOT EXISTS cancel_reason TEXT NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'instance_tasks_command_check'
    ) THEN
        ALTER TABLE instance_tasks DROP CONSTRAINT instance_tasks_command_check;
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'instance_tasks_command_check_async'
    ) THEN
        ALTER TABLE instance_tasks DROP CONSTRAINT instance_tasks_command_check_async;
    END IF;

    ALTER TABLE instance_tasks
        ADD CONSTRAINT instance_tasks_command_check_async
        CHECK (command IN ('create', 'update', 'delete', 'start', 'stop'));
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'instance_tasks_status_check'
    ) THEN
        ALTER TABLE instance_tasks DROP CONSTRAINT instance_tasks_status_check;
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'instance_tasks_status_check_async'
    ) THEN
        ALTER TABLE instance_tasks DROP CONSTRAINT instance_tasks_status_check_async;
    END IF;

    ALTER TABLE instance_tasks
        ADD CONSTRAINT instance_tasks_status_check_async
        CHECK (status IN ('queued', 'running', 'cancel_pending', 'succeeded', 'failed', 'canceled'));
END $$;

CREATE INDEX IF NOT EXISTS instance_tasks_instance_id_idx ON instance_tasks (instance_id);
CREATE INDEX IF NOT EXISTS instance_tasks_status_idx ON instance_tasks (status);

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'operator', 'viewer')),
    tenant_id UUID NULL REFERENCES tenants (id),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id UUID NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'users_tenant_id_fkey'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_tenant_id_fkey
            FOREIGN KEY (tenant_id)
            REFERENCES tenants (id);
    END IF;
END $$;

UPDATE users
SET tenant_id = NULL
WHERE role = 'admin';

UPDATE users
SET tenant_id = '00000000-0000-0000-0000-000000000001'
WHERE role IN ('operator', 'viewer') AND tenant_id IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'users_tenant_role_check'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_tenant_role_check
            CHECK (
                (role = 'admin' AND tenant_id IS NULL)
                OR (role IN ('operator', 'viewer') AND tenant_id IS NOT NULL)
            );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS users_role_idx ON users (role);
CREATE INDEX IF NOT EXISTS users_tenant_id_idx ON users (tenant_id);

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
    tenant_id UUID NULL REFERENCES tenants (id),
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

ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS tenant_id UUID NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'audit_logs_tenant_id_fkey'
    ) THEN
        ALTER TABLE audit_logs
            ADD CONSTRAINT audit_logs_tenant_id_fkey
            FOREIGN KEY (tenant_id)
            REFERENCES tenants (id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS audit_logs_created_at_idx ON audit_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS audit_logs_actor_user_id_idx ON audit_logs (actor_user_id);
CREATE INDEX IF NOT EXISTS audit_logs_action_idx ON audit_logs (action);
CREATE INDEX IF NOT EXISTS audit_logs_target_type_idx ON audit_logs (target_type);
CREATE INDEX IF NOT EXISTS audit_logs_request_id_idx ON audit_logs (request_id);
CREATE INDEX IF NOT EXISTS audit_logs_tenant_id_idx ON audit_logs (tenant_id);

CREATE OR REPLACE VIEW resource_reservations_view AS
SELECT
    host_node,
    COALESCE(SUM(cpu) FILTER (WHERE status <> 'stopped'), 0) AS reserved_cpu,
    COALESCE(SUM(memory_mib) FILTER (WHERE status <> 'stopped'), 0) AS reserved_memory_mib,
    COALESCE(SUM(disk_gib), 0) AS reserved_disk_gib
FROM instances
WHERE reserve_resources = true
  AND status <> 'deleted'
GROUP BY host_node;

CREATE OR REPLACE VIEW tenant_resource_usage_view AS
SELECT
    tenant_id,
    COUNT(*) FILTER (WHERE reserve_resources = true AND status <> 'deleted') AS used_instances,
    COALESCE(SUM(cpu) FILTER (WHERE reserve_resources = true AND status <> 'deleted' AND status <> 'stopped'), 0) AS used_cpu,
    COALESCE(SUM(memory_mib) FILTER (WHERE reserve_resources = true AND status <> 'deleted' AND status <> 'stopped'), 0) AS used_memory_mib,
    COALESCE(SUM(disk_gib) FILTER (WHERE reserve_resources = true AND status <> 'deleted'), 0) AS used_disk_gib
FROM instances
GROUP BY tenant_id;
