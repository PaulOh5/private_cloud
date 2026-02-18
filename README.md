# VM Private Cloud MVP

This repository contains an MSA MVP with three services:
- `main-api`: FastAPI + PostgreSQL (DDD/CQRS + repository + ports/adapters)
- `vm-manager`: Go + QEMU worker controlled via RabbitMQ
- `frontend`: React + TypeScript 운영 콘솔 (Nginx 정적 서빙, `/api` 프록시)

## Quick Project Overview (for new Codex sessions)
- Goal: single-host VM private cloud MVP with async VM lifecycle orchestration.
- Services:
  - `main-api` (Python/FastAPI/PostgreSQL): REST API, DDD/CQRS, auth/RBAC, task tracking, audit logs.
  - `vm-manager` (Go/QEMU): executes VM create/update/delete + network setup.
- Tenancy/Quota:
  - Multi-tenant model with `tenants` + per-tenant hard quota (`instances/cpu/memory/disk`).
  - Quota is enforced on `create/update/retry`.
  - `stopped` instances keep `instances/disk` reserved, but release `cpu/memory`; `start` re-checks quota.
  - `admin` can operate across tenants, `operator/viewer` are tenant-scoped.
- Communication:
  - Command path: `main-api -> RabbitMQ(vm.commands) -> vm-manager`
  - Result path: `vm-manager -> RabbitMQ(vm.results) -> main-api` background consumer
  - Console path: `frontend(noVNC) -> main-api(console ticket + WS proxy) -> vm-manager/QEMU VNC`
- API behavior:
  - `POST/PUT/DELETE /instances` are async (`202 Accepted + task_id`)
  - Progress/result via `GET /tasks` / `GET /tasks/{id}`
- Auth/Security:
  - JWT access + refresh token rotation, logout(revoke), role-based access (`admin/operator/viewer`)
  - User/role management APIs and audit log APIs are included.
  - VM web console is ticket-based (5 min TTL, single-use) and limited to `admin/operator`.
- Persistence:
  - PostgreSQL stores tenants, tenant quotas, instances, tasks, users, refresh tokens, audit logs.
- Deployment baseline:
  - `docker-compose` for `main-api`, `postgres`, `rabbitmq`
  - `vm-manager` runs with host-level privileges for QEMU/network operations.
  - VM egress networking: `vm-manager` enables IPv4 forwarding and installs interface-scoped iptables NAT/forward rules for `172.30.0.0/16` using dedicated chains (`VM_MANAGER_FORWARD`, `VM_MANAGER_NAT`) with `vm-manager` comments (`br+` bridge matching).

## Security notice
This is development/PoC only. VM root password is intentionally fixed to `1234` and must never be used in production.

## Quickstart
1. `cp .env.example .env`
2. If host ports conflict, override exposed ports in `.env`:
   - `POSTGRES_EXPOSE_PORT`, `RABBITMQ_EXPOSE_PORT`, `RABBITMQ_MGMT_EXPOSE_PORT`
   - `MAIN_API_PORT`, `FRONTEND_PORT`
   - Host capacity baseline: `TOTAL_CPU`, `TOTAL_MEMORY_MIB`, `TOTAL_DISK_GIB`, `TOTAL_INSTANCES`
   - Optional noVNC console: `CONSOLE_TICKET_TTL_SECONDS` (default `300`), `CONSOLE_PROXY_HOST` (default `host.docker.internal`), `CONSOLE_VNC_PORT_BASE` (default `20000`), `CONSOLE_VNC_PORT_SPAN` (default `40000`)
   - Optional stale-task recovery: `TASK_STALE_QUEUED_TIMEOUT_SECONDS` (default `180`), `TASK_STALE_SWEEP_INTERVAL_SECONDS` (default `15`, set `0` to disable)
   - Optional VM egress interface override: `VM_EGRESS_INTERFACE` (default route interface is auto-detected)
   - Optional VM network cleanup interval: `VM_NETWORK_CLEANUP_INTERVAL_SECONDS` (default `300`, set `0` to disable)
   - Optional VM image catalog:
     - `BASE_IMAGE_URL` keeps legacy single-image fallback
     - If catalog env is empty, built-in defaults are available: `ubuntu-24.04` and `ubuntu-22.04`
     - `VM_IMAGE_CATALOG_JSON` to configure multiple images (`id/url/sha256/format/is_default`)
     - `VM_IMAGE_DEFAULT_ID` to force default image id
     - `VM_IMAGE_ALLOW_INSECURE_NO_CHECKSUM` (default `false`)
3. `docker compose up --build`
4. Open:
   - Frontend: `http://localhost:3000` (or `FRONTEND_PORT`)
   - API docs (direct): `http://localhost:8000/docs`
   - API docs (via frontend proxy): `http://localhost:3000/api/docs`

## Frontend guide (Korean UI)
### Default account
- `username`: `admin`
- `password`: `admin1234`

### First-login flow (for beginners)
1. 로그인 후 `인스턴스` 화면에서 현재 VM 목록을 확인합니다.
2. `인스턴스 생성` 버튼으로 VM 요청을 생성합니다.
3. `작업 이력` 화면에서 `queued/running/succeeded/failed` 상태 변화를 확인합니다.
4. `인스턴스 상세`에서 `웹 콘솔(noVNC)` 버튼으로 SSH 없이 VM 콘솔에 접속합니다.
5. 관리자 계정이면 `사용자 관리`에서 operator/viewer 계정을 분리 생성합니다.
6. `감사 로그`에서 로그인/권한/리소스 작업 이벤트를 점검합니다.

### RBAC behavior
- `admin`: 전체 기능 + cross-tenant 운영 (`/tenants` API 포함)
- `operator`: 자기 tenant 인스턴스/태스크 조회 + 생성/수정/삭제 요청 + VM 웹 콘솔
- `viewer`: 자기 tenant 인스턴스/태스크 조회 전용

## Services and queues
- Command exchange: `vm.commands`
- Command queue: `vm.commands.q`
- Result exchange: `vm.results`
- Main-api result queue: `main-api.vm-results.q`
- Dead-letter queue: `vm.commands.dlq`

## Async endpoints
- `POST /auth/login` (get JWT bearer token)
- `POST /auth/refresh` (rotate refresh token + issue new access token)
- `POST /auth/logout` (revoke refresh token)
- `GET /auth/me` (token check)
- `GET /roles` (admin)
- `GET /users` (admin)
- `GET /users/{id}` (admin or self)
- `POST /users` (admin)
- `PATCH /users/{id}` (admin)
- `DELETE /users/{id}` (admin, soft deactivate)
- `POST /tenants` (admin)
- `GET /tenants` (admin)
- `GET /tenants/{id}` (admin)
- `PATCH /tenants/{id}` (admin)
- `PATCH /tenants/{id}/quota` (admin)
- `GET /tenants/{id}/usage` (admin)
- `DELETE /tenants/{id}` (admin, empty tenant only)
- `GET /audit-logs` (admin)
- `GET /audit-logs/{id}` (admin)
- `GET /images` (viewer/operator/admin)
- `POST /images/sync` (admin, sync/prefetch image cache)
- `POST /instances` -> `202 + task_id`
  - request field: `tenant_id` (admin required, operator/viewer server-enforced to own tenant)
  - optional request field: `image_id` (if omitted, vm-manager default image is used)
- `PUT /instances/{id}` -> `202 + task_id`
- `DELETE /instances/{id}` -> `202 + task_id`
- `POST /instances/{id}/stop` -> `202 + task_id`
- `POST /instances/{id}/start` -> `202 + task_id`
- `GET /instances` (admin can filter by `tenant_id`)
- `GET /instances/{id}`
- `POST /instances/{id}/console-ticket` (operator/admin)
- `WS /instances/{id}/console/ws?ticket=...` (single-use ticket required)
- `GET /tasks` (admin can filter by `tenant_id`)
- `GET /tasks/{id}`
- `POST /tasks/{id}/retry` -> `202 + new task_id`
- `POST /tasks/{id}/cancel` -> `202 + cancel_pending|canceled`

All `/images`, `/instances`, and `/tasks` endpoints require `Authorization: Bearer <token>`.

## Breaking changes (tenant phase)
- `POST /instances`: `admin` must provide `tenant_id`.
- `POST /users`: `operator/viewer` creation requires `tenant_id`; `admin` must not have `tenant_id`.
- `PATCH /users/{id}`: role/tenant consistency is enforced (`admin -> tenant_id=null`, non-admin -> tenant_id required).

## Web console notes (noVNC)
- Designed for single-host `docker-compose` PoC.
- `main-api` proxies WebSocket traffic to host QEMU VNC ports using `CONSOLE_PROXY_HOST`.
- Ticket policy: 1-time use, expires in 5 minutes by default.
- QEMU VNC ports are exposed on host range derived from `CONSOLE_VNC_PORT_BASE` and `CONSOLE_VNC_PORT_SPAN`; enforce host firewall/network restrictions in non-local environments.

## State model
- Instance: `creating_pending | updating_pending | starting_pending | stopping_pending | deleting_pending | running | stopped | error | deleted`
- Task: `queued | running | cancel_pending | succeeded | failed | canceled`

## Testing `frontend`
### Install dependencies
```bash
cd frontend
npm install
```

### Run tests
```bash
cd frontend
npm run test
```

### Build
```bash
cd frontend
npm run build
```

## Testing `main-api`
### Prerequisites
1. Python venv is available at `main-api/.venv`
2. Docker daemon is running (required for integration tests using Testcontainers)

### Install dependencies
```bash
cd main-api
.venv/bin/pip install -r requirements.txt
```

### Run unit tests
```bash
cd main-api
PYTHONPATH=. .venv/bin/python -m pytest -q tests/unit
```

### Run integration tests
```bash
cd main-api
PYTHONPATH=. .venv/bin/python -m pytest -q tests/integration -m integration
```

### Run all tests
```bash
cd main-api
PYTHONPATH=. .venv/bin/python -m pytest -q
```

### Notes
1. Integration tests spin up PostgreSQL containers via `testcontainers`.
2. If Docker is not available, integration tests may fail or be skipped depending on environment.
