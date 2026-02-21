# Main API 코드리뷰 묶음

`main-api` 백엔드 리뷰 결과를 주제별로 분리한 문서입니다.

- `01-consistency-and-messaging.md`
  - 트랜잭션/메시징 일관성, MQ 결과 소비 안정성
- `02-auth-and-token-rotation.md`
  - 인증/리프레시 토큰 회전 동시성 이슈
- `03-console-and-access-control.md`
  - 콘솔 경로 가용성/접근통제 이슈
- `04-validation-and-error-mapping.md`
  - 입력 검증/예외 매핑
- `05-performance-and-observability.md`
  - N+1, 추적성(request_id) 개선
- `06-testing-gaps.md`
  - 현재 테스트 커버리지 공백

테스트 실행 기준:
- Unit: `32 passed`
- Integration: `29 passed`
