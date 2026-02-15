# Task Retry/Cancel API Implementation Plan

## 1. Goal
Add operational APIs to retry failed VM lifecycle tasks and cancel in-flight tasks.

- Retry: recreate a new task from a previous failed/canceled task.
- Cancel: stop queued/running work with clear terminal outcome.
- Keep auditability and idempotency.

## 2. Current Context
- `main-api` is async task-based:
  - `POST/PUT/DELETE /instances` -> `202 + task_id`
  - current task statuses: `queued | running | succeeded | failed`
- `vm-manager` consumes commands via RabbitMQ and emits result events.
- DB has `instances`, `instance_tasks`, auth/audit tables.
- Same-instance active task conflict policy already exists.

## 3. Scope

### In scope
1. `POST /tasks/{task_id}/retry`
2. `POST /tasks/{task_id}/cancel`
3. Task state extension for cancel flow
4. Result processing for canceled outcomes
5. RabbitMQ contract extension for cancel command/result status
6. Audit logging for retry/cancel actions
7. Unit/integration tests

### Out of scope (MVP)
1. Full checkpoint rollback orchestration
2. Hard guarantees for cancel preemption at every step

## 4. API Contract

### 4.1 Retry
`POST /tasks/{task_id}/retry`

- Auth: `operator | admin`
- Preconditions:
  - original task status in `failed | canceled`
  - no active task on same instance (`queued | running | cancel_pending`)
- Behavior:
  - clone payload/command into a **new task**
  - generate new `task_id`, `request_id`, timestamps
  - publish corresponding command
  - return `202`

Response:
```json
{
  "task_id": "new-task-uuid",
  "instance_id": "instance-uuid",
  "status": "queued",
  "command": "create|update|delete",
  "accepted_at": "2026-02-15T12:00:00Z"
}
```

Errors: `404`, `409`, `400`

### 4.2 Cancel
`POST /tasks/{task_id}/cancel`

- Auth: `operator | admin`
- Allowed source statuses: `queued`, `running`
- Behavior:
  - `queued` -> immediate `canceled` (local cancel)
  - `running` -> `cancel_pending` + publish `instance.cancel`
  - terminal task cancel request: idempotent success recommended

Response:
```json
{
  "task_id": "task-uuid",
  "instance_id": "instance-uuid",
  "status": "cancel_pending|canceled",
  "command": "create|update|delete",
  "accepted_at": "2026-02-15T12:00:00Z"
}
```

## 5. Data Model Changes

### 5.1 instance_tasks status extension
Add statuses:
- `cancel_pending`
- `canceled`

Final set:
- `queued | running | cancel_pending | succeeded | failed | canceled`

### 5.2 Optional columns (recommended)
- `retry_of_task_id UUID NULL`
- `canceled_by UUID NULL`
- `cancel_reason TEXT NULL`

(If minimizing schema changes, store these in payload metadata.)

## 6. RabbitMQ Contract Changes

### 6.1 New command routing key
- `instance.cancel`

Payload example:
```json
{
  "task_id": "...",
  "request_id": "...",
  "instance_id": "...",
  "command": "cancel",
  "payload": {
    "target_task_id": "...",
    "target_command": "create|update|delete",
    "reason": "optional"
  },
  "timestamp": "..."
}
```

### 6.2 Result status extension
- support `canceled` in result events (`running|succeeded|failed|canceled`)

## 7. State Transition Rules

### Task
- `queued -> running -> succeeded|failed|canceled`
- `queued -> canceled` (immediate local cancel)
- `running -> cancel_pending -> canceled|failed|succeeded`

### Instance
Reuse existing failure rollback policy for canceled outcomes:
- cancel create: release reserved resources, set safe terminal (`error` recommended)
- cancel update: rollback previous spec
- cancel delete: keep instance undeleted and reservation consistent

## 8. Main-API Implementation Steps
1. Migration: task status constraint update (+ optional columns)
2. Domain: extend `TaskStatus`
3. Repository: add `mark_cancel_pending`, `mark_canceled`, `clone_for_retry`
4. Application handlers:
   - `RetryTaskCommandHandler`
   - `CancelTaskCommandHandler`
5. API routes:
   - `POST /tasks/{id}/retry`
   - `POST /tasks/{id}/cancel`
6. Result processor: handle `canceled` terminal event idempotently
7. Audit:
   - `task.retry.requested`
   - `task.cancel.requested`
   - `task.cancel.completed|failed`

## 9. VM-Manager Implementation Steps
1. Parse/validate `instance.cancel`
2. Track in-flight operations by task/instance
3. Attempt graceful cancel and emit `canceled` when successful
4. If operation already completed, emit actual terminal (`succeeded|failed`)
5. Maintain idempotency by request/task key

## 10. Concurrency and Idempotency
1. Active task set: `queued|running|cancel_pending` (one per instance)
2. Retry rejected if active task exists
3. Cancel endpoint idempotent for repeated requests
4. Use transaction + `FOR UPDATE` for task/instance transitions

## 11. Test Plan

### Unit (main-api)
1. Retry from failed creates new queued task + publish
2. Retry blocked by active task (`409`)
3. Cancel queued => canceled
4. Cancel running => cancel_pending + publish cancel
5. Duplicate cancel idempotent
6. Result processor handles canceled correctly

### Integration (main-api)
1. Retry API returns `202` and new task row
2. Cancel queued updates row terminally
3. Cancel running sets `cancel_pending`
4. Audit logs written for retry/cancel

### Unit (vm-manager)
1. cancel command parsing
2. in-flight cancel signal behavior
3. result emission correctness

### E2E
1. failed task retry success path
2. long-running task cancel path
3. delete-cancel policy validation

## 12. Acceptance Criteria
1. Retry/Cancel endpoints exist and documented
2. Retry returns new task (`202`)
3. Cancel works for queued/running
4. Task status includes `cancel_pending|canceled`
5. `main-api` handles canceled result events idempotently
6. Audit logs exist for retry/cancel actions
7. Tests pass in CI

## 13. Recommended Order
1. migration + status model
2. repository + command handlers
3. API + schemas
4. result processor
5. vm-manager cancel support
6. tests