# 입력 검증/예외 매핑 리뷰

## High: 사용자 생성/수정 시 잘못된 tenant_id가 500으로 노출될 가능성

- 문제
  - `users` 쓰기 로직에서 tenant FK 위반이 발생하면, API 레이어에서 명시적으로 매핑하지 않아 500으로 보일 수 있습니다.
- 근거
  - 사용자 생성:
    - `main-api/app/api/user_routes.py:99`
    - `main-api/app/adapters/postgres.py:652`
  - 사용자 수정:
    - `main-api/app/api/user_routes.py:157`
    - `main-api/app/adapters/postgres.py:756`
- 영향
  - 클라이언트 입장에서 잘못된 입력이 서버 장애처럼 보임
  - 운영 모니터링 노이즈 증가
- 권장
  - API 진입 시 tenant 존재성 사전 검증
  - 또는 저장소에서 `IntegrityError`를 `HTTP 400/404`로 매핑

## 보완 제안

- 예외 정책 표준화
  - DomainError 매핑은 `main-api/app/main.py:190`에서 처리 중
  - DB 무결성 예외를 DomainError로 래핑하여 일관 응답 유지 권장
