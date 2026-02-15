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
- Communication:
  - Command path: `main-api -> RabbitMQ(vm.commands) -> vm-manager`
  - Result path: `vm-manager -> RabbitMQ(vm.results) -> main-api` background consumer
- API behavior:
  - `POST/PUT/DELETE /instances` are async (`202 Accepted + task_id`)
  - Progress/result via `GET /tasks` / `GET /tasks/{id}`
- Auth/Security:
  - JWT access + refresh token rotation, logout(revoke), role-based access (`admin/operator/viewer`)
  - User/role management APIs and audit log APIs are included.
- Persistence:
  - PostgreSQL stores instances, tasks, users, refresh tokens, audit logs.
- Deployment baseline:
  - `docker-compose` for `main-api`, `postgres`, `rabbitmq`
  - `vm-manager` runs with host-level privileges for QEMU/network operations.

## Security notice
This is development/PoC only. VM root password is intentionally fixed to `1234` and must never be used in production.

## Quickstart
1. `cp .env.example .env`
2. If host ports conflict, override exposed ports in `.env`:
   - `POSTGRES_EXPOSE_PORT`, `RABBITMQ_EXPOSE_PORT`, `RABBITMQ_MGMT_EXPOSE_PORT`
   - `MAIN_API_PORT`, `FRONTEND_PORT`
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
4. 관리자 계정이면 `사용자 관리`에서 operator/viewer 계정을 분리 생성합니다.
5. `감사 로그`에서 로그인/권한/리소스 작업 이벤트를 점검합니다.

### RBAC behavior
- `admin`: 전체 기능 (인스턴스/태스크/사용자/감사로그)
- `operator`: 인스턴스/태스크 조회 + 생성/수정/삭제 요청
- `viewer`: 인스턴스/태스크 조회 전용

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
- `GET /audit-logs` (admin)
- `GET /audit-logs/{id}` (admin)
- `POST /instances` -> `202 + task_id`
- `PUT /instances/{id}` -> `202 + task_id`
- `DELETE /instances/{id}` -> `202 + task_id`
- `GET /instances`
- `GET /instances/{id}`
- `GET /tasks`
- `GET /tasks/{id}`

All `/instances` and `/tasks` endpoints require `Authorization: Bearer <token>`.

## State model
- Instance: `creating_pending | updating_pending | deleting_pending | running | stopped | error | deleted`
- Task: `queued | running | succeeded | failed`

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
PYTHONPATH=. .venv/bin/pytest -q tests/unit
```

### Run integration tests
```bash
cd main-api
PYTHONPATH=. .venv/bin/pytest -q tests/integration -m integration
```

### Run all tests
```bash
cd main-api
PYTHONPATH=. .venv/bin/pytest -q
```

### Notes
1. Integration tests spin up PostgreSQL containers via `testcontainers`.
2. If Docker is not available, integration tests may fail or be skipped depending on environment.
