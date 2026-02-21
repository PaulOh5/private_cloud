# 테스트 커버리지 공백

현재 테스트 상태:
- Unit: `32 passed`
- Integration: `29 passed`

## 미검증/약검증 영역

1. 메시징-트랜잭션 원자성 실패 케이스
- MQ 발행 성공 + DB 커밋 실패 시나리오 검증 부재
- 대상 흐름:
  - `main-api/app/application/commands/*.py`
  - `main-api/app/api/routes.py`

2. 결과 컨슈머 ACK 정책 검증 부재
- 일반 예외 발생 시 ACK/NACK 동작에 대한 테스트 부족
- 대상:
  - `main-api/app/adapters/rabbitmq_result_consumer.py:104`

3. refresh token 동시성 레이스 테스트 부재
- 동일 refresh token으로 동시 `POST /auth/refresh` 요청 시 단일 성공 보장 테스트 필요
- 대상:
  - `main-api/app/api/auth_routes.py`
  - `main-api/app/adapters/postgres.py`

4. 콘솔 포트 충돌/재할당 정책 테스트 부재
- 서로 다른 instance_id가 같은 포트로 매핑되는 경우 처리 검증 필요
- 대상:
  - `main-api/app/application/services/console_port.py`
  - `vm-manager/internal/infra/console.go`

5. 사용자 tenant FK 예외 매핑 테스트 부재
- 존재하지 않는 tenant_id로 user create/update 시 4xx 응답 보장 테스트 필요
- 대상:
  - `main-api/app/api/user_routes.py`
  - `main-api/app/adapters/postgres.py`

## 추천 테스트 추가 순서

1. refresh 동시성 레이스
2. 컨슈머 ACK/NACK/DLQ 분기
3. outbox(또는 커밋 후 발행) 일관성
4. 콘솔 포트 충돌 정책
5. tenant FK 예외 매핑
