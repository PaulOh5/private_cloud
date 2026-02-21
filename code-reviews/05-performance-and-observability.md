# 성능/관측성 리뷰

## High: 테넌트 목록 조회 N+1 쿼리

- 문제
  - 테넌트 목록 조회 후 각 테넌트마다 quota를 별도 조회합니다.
- 근거
  - `main-api/app/api/tenant_routes.py:112`
  - `main-api/app/api/tenant_routes.py:113`
- 영향
  - tenant 수가 많아질수록 응답 지연 및 DB 부하 증가
- 권장
  - tenant + tenant_quotas 조인 조회
  - 또는 배치 조회 후 메모리 매핑

## Medium: audit request_id 추적성 약화

- 문제
  - `x-request-id`가 없으면 audit 기록마다 임의 UUID를 생성하여 동일 요청 내 이벤트 상관관계가 깨집니다.
- 근거
  - `main-api/app/api/audit.py:16`
- 영향
  - 장애 분석/추적 난이도 증가
- 권장
  - request lifecycle 시작 시 request_id를 1회 생성
  - `request.state.request_id`를 모든 audit write에서 재사용
