# 일관성/메시징 안정성 리뷰

## Critical 1: DB 커밋 전 MQ 발행으로 인한 고아 작업 위험

- 문제
  - 커맨드 핸들러 내부에서 `publish_command()`를 먼저 호출하고, API 레이어에서 나중에 `session.commit()`을 수행합니다.
  - MQ 발행은 성공했지만 DB 커밋이 실패하면, 워커는 존재하지 않는 task/instance를 처리하게 됩니다.
- 근거
  - 발행 지점:
    - `main-api/app/application/commands/create_instance.py:119`
    - `main-api/app/application/commands/update_instance.py:130`
    - `main-api/app/application/commands/delete_instance.py:79`
    - `main-api/app/application/commands/start_instance.py:113`
    - `main-api/app/application/commands/stop_instance.py:78`
    - `main-api/app/application/commands/retry_task.py:100`
    - `main-api/app/application/commands/cancel_task.py:71`
  - 커밋 지점:
    - `main-api/app/api/routes.py:202`
    - `main-api/app/api/routes.py:253`
    - `main-api/app/api/routes.py:292`
    - `main-api/app/api/routes.py:373`
    - `main-api/app/api/routes.py:639`
    - `main-api/app/api/routes.py:715`
- 영향
  - 상태 불일치, 복구 난이도 상승, 운영 중 pending 고착 가능성 증가
- 권장
  - Outbox 패턴 도입
  - DB 트랜잭션 내 outbox 레코드 저장 후 별도 퍼블리셔가 발행/재시도

## Critical 2: 결과 컨슈머가 일반 예외를 ACK하여 이벤트 유실

- 문제
  - 결과 처리 중 예외가 발생해도 `basic_ack` 처리되어 메시지가 사라집니다.
- 근거
  - `main-api/app/adapters/rabbitmq_result_consumer.py:104`
  - `main-api/app/adapters/rabbitmq_result_consumer.py:106`
- 영향
  - task 상태가 `queued/running/cancel_pending`에 고착될 수 있음
- 권장
  - 재시도 가능 예외는 `basic_nack(requeue=True)` 유지
  - 재시도 불가 메시지는 DLQ 라우팅
  - 예외 유형별 분기 정책 명확화

## 권장 우선순위

1. Outbox 도입 또는 최소한 커밋 이후 발행 구조로 전환
2. 컨슈머 ACK 정책 수정 + DLQ 전략 확정
