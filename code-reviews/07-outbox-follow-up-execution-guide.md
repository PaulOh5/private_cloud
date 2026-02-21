# Outbox 후속 과제 실행 가이드

이 문서는 Outbox 도입 이후 남은 후속 과제를 다음 Codex 세션에서 바로 이어서 수행할 수 있도록 정리한 작업 문서입니다.

## 현재 상태 요약

- 완료
  - Command write-path가 Outbox 적재 기반으로 전환됨
  - `OutboxRelay`(LISTEN/NOTIFY + polling) 동작
  - Result consumer ACK/DLQ 정책 도입
  - `rabbitmq_rpc`의 결과 큐 선언 제거(큐 인자 충돌 재발 방지)
- 확인된 운영 이슈
  - 과거 큐 토폴로지와 신규 DLQ 정책이 충돌하면 `PRECONDITION_FAILED`가 발생할 수 있음
  - stale monitor 타이밍으로 일부 task가 `TIMEOUT`으로 종료될 수 있어 재처리 절차 필요

## 후속 과제 우선순위

1. vm-manager 멱등/중복 실행 방지
2. outbox 실패(`failed`) 자동 재큐잉/운영 자동화
3. 메시징/relay/consumer 관측성 강화
4. 큐 토폴로지 마이그레이션 자동 점검 스크립트
5. 회귀 테스트 보강(특히 토폴로지 충돌/복구 시나리오)

---

## 1) vm-manager 멱등/중복 실행 방지

### 배경
- 현재는 동일 `task_id/request_id`가 재발행될 경우 vm-manager에서 중복 실행될 가능성이 남아 있음.

### 목표
- 같은 요청이 중복 전달되어도 실제 VM 작업은 1회만 실행되게 보장.

### 구현 작업
- `vm-manager`에 dedupe 저장소 추가(권장: PostgreSQL 또는 Redis).
- 키 설계
  - 우선순위: `request_id` + `command`
  - 보조: `task_id`
- 처리 정책
  - 수신 시 dedupe 키 조회
  - 이미 성공 처리된 키면 즉시 성공 결과 재발행(또는 no-op 처리)
  - 처리 중 상태면 중복 실행 차단
- 후보 파일
  - `vm-manager/internal/rpc/server.go`
  - `vm-manager/internal/service/*`
  - 신규 저장소 어댑터 파일(예: `vm-manager/internal/infra/dedupe_*`)

### 완료 기준(DoD)
- 동일 메시지 2회 주입 시 VM 생성/수정/삭제 실제 작업이 1회만 수행됨.
- 중복 건은 로그/메트릭으로 식별 가능함.

### 검증
- integration test:
  - 동일 `request_id`로 명령 2회 발행
  - 결과 이벤트는 정책대로 나오고 실제 side effect는 1회인지 검증

---

## 2) Outbox failed 자동 재큐잉/운영 자동화

### 배경
- 현재 `command_outbox.status='failed'`는 수동 대응에 의존.

### 목표
- 재시도 가능한 실패는 운영자가 안전하게 재큐잉 가능하고, 반복되는 실패는 원인 파악이 쉬워야 함.

### 구현 작업
- 관리용 SQL/스크립트 추가
  - 단건 재큐잉
  - 기간/토픽 기준 일괄 재큐잉
  - `attempt_count`/`next_attempt_at`/`last_error` 처리 정책 명시
- 최소 1개 운영 엔드포인트 또는 CLI 추가(내부 전용)
  - 예: `scripts/outbox_requeue.sh`
- 후보 파일
  - `main-api/scripts/*` (신규)
  - `main-api/docs/*` (런북 문서)
  - 필요 시 `main-api/app/api/admin_*` (운영 전용 API)

### 완료 기준(DoD)
- `failed` row를 재큐잉하면 `queued -> sent`로 회복됨.
- 재큐잉 작업 전/후 점검 쿼리가 문서화됨.

### 검증
- 실패 유도 후 재큐잉 시나리오 E2E 테스트 1개 이상.

---

## 3) 관측성(메트릭/알람/로그) 강화

### 배경
- Outbox/Relay/Consumer 동작은 기능적으로 들어갔지만, 지표 기반 운영은 아직 약함.

### 목표
- 적체/실패/지연을 조기 감지할 수 있는 최소 지표와 알람 기준 확보.

### 구현 작업
- 로그 구조화
  - outbox id, task_id, request_id, topic, attempt_count 포함
- 메트릭 추가(최소)
  - outbox queued count
  - outbox failed count
  - outbox oldest queued age
  - relay publish success/failure counter
  - result DLQ 유입량
- 대시보드/알람 문서화
  - 임계치 기본값 제안 포함
- 후보 파일
  - `main-api/app/adapters/outbox_relay.py`
  - `main-api/app/adapters/rabbitmq_result_consumer.py`
  - `main-api/docs/observability-*`

### 완료 기준(DoD)
- 장애 상황(예: RabbitMQ down)에서 어떤 지표가 상승하는지 확인 가능.
- 알람 기준이 문서로 고정됨.

---

## 4) RabbitMQ 토폴로지 마이그레이션 자동 점검

### 배경
- 큐 인자 불일치(`x-dead-letter-exchange`)는 배포 후 장애를 유발함.

### 목표
- 앱 시작 전/배포 직후 토폴로지 불일치를 자동 탐지하고 조치 가능하게 함.

### 구현 작업
- 점검 스크립트 추가
  - 큐 존재/인자 비교
  - 기대 인자와 다르면 경고 + 복구 가이드 출력
- 선택 과제
  - non-prod에서는 자동 삭제/재생성 옵션
- 후보 파일
  - `scripts/check_rabbitmq_topology.sh` (신규)
  - `docs/runbook-rabbitmq-topology.md` (신규)

### 완료 기준(DoD)
- 배포 파이프라인 또는 수동 점검에서 토폴로지 drift를 즉시 식별 가능.

---

## 5) 회귀 테스트 보강

### 목표
- 이번 장애 유형(큐 인자 충돌, 결과 적체, stale timeout 연동)을 테스트로 고정.

### 추가 권장 테스트
- `main-api/tests/integration/test_postgres_async_flow.py`
  - 결과 큐 인자 충돌 상황 재현 테스트(사전 선언 큐 인자 mismatch)
  - 복구 후 정상 처리 테스트
- `main-api/tests/unit/test_rabbitmq_result_consumer.py`
  - retryable/non-retryable 예외 분기
  - DLQ 라우팅 분기
- `main-api/tests/unit/test_async_handlers.py`
  - outbox enqueue 파라미터(특히 `max_attempts`) 검증

### 완료 기준(DoD)
- 이번에 겪은 장애가 테스트에서 재현/검출 가능.
- `pytest -q` 전체 통과.

---

## 다음 세션 작업 순서(권장)

1. `vm-manager` dedupe 설계/구현
2. outbox 재큐잉 스크립트 + runbook
3. 관측성 지표/로그 보강
4. 토폴로지 점검 스크립트
5. 회귀 테스트 보강 및 전체 테스트 통과

## 다음 세션 시작 체크리스트

- [ ] `docker compose ps`로 컨테이너 상태 확인
- [ ] `main-api.vm-results.q` 인자 확인
- [ ] `command_outbox` 상태 분포 확인(`queued/publishing/sent/failed`)
- [ ] 최근 24시간 `instance_tasks`에서 `failed/TIMEOUT` 비율 확인

## 참고 명령어

```bash
# RabbitMQ 큐 상태/인자
docker exec -i private_cloud-rabbitmq-1 rabbitmqctl list_queues name messages_ready messages_unacknowledged arguments

# Outbox 상태 분포
docker exec -i private_cloud-postgres-1 psql -U cloud -d private_cloud -c \
  "SELECT status, count(*) FROM command_outbox GROUP BY status ORDER BY status;"

# 오래된 queued outbox
docker exec -i private_cloud-postgres-1 psql -U cloud -d private_cloud -c \
  "SELECT now() - min(created_at) AS oldest_age FROM command_outbox WHERE status='queued';"

# 최근 task 상태
docker exec -i private_cloud-postgres-1 psql -U cloud -d private_cloud -c \
  "SELECT status, count(*) FROM instance_tasks WHERE created_at > now() - interval '24 hours' GROUP BY status ORDER BY status;"
```
