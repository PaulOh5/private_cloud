# 인증/토큰 회전 리뷰

## High: Refresh Token 회전의 동시성 취약점

- 문제
  - 동일 refresh token으로 동시 요청이 들어오면, 복수의 새 토큰이 발급될 수 있습니다.
  - 현재 revoke 쿼리에 `revoked_at IS NULL` 가드가 없어 CAS(compare-and-set) 보장이 없습니다.
- 근거
  - 회전 흐름:
    - `main-api/app/api/auth_routes.py:126`
    - `main-api/app/api/auth_routes.py:165`
  - revoke 구현:
    - `main-api/app/adapters/postgres.py:835`
- 영향
  - 세션 회전 정책 약화
  - 탈취된 refresh token의 악용 창(window) 확대 가능
- 권장
  - `UPDATE ... WHERE token_hash=:hash AND revoked_at IS NULL RETURNING *`
  - 반환 행이 있을 때만 새 토큰 발급
  - 필요 시 refresh 처리 전체를 트랜잭션+락(또는 고유 상태 전이)로 강화

## 추가 점검 포인트

- `/auth/logout` 경로는 현재 access token 사용자와 refresh token 소유자가 일치할 때만 revoke 수행
  - `main-api/app/api/auth_routes.py:189`
- 보안적으로 타당하나, 운영 관점에서 다중 디바이스 정책(단일 logout vs 전체 logout) 문서화 필요
