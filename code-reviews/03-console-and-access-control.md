# 콘솔 경로/접근통제 리뷰

## High 1: 콘솔 포트 해시 매핑 충돌에 따른 가용성 리스크

- 문제
  - 인스턴스 ID 해시 기반으로 VNC 포트를 고정 매핑하지만 충돌 회피 로직이 없습니다.
- 근거
  - main-api 포트 계산:
    - `main-api/app/application/services/console_port.py:4`
    - `main-api/app/api/routes.py:478`
  - vm-manager도 동일 해시 매핑 사용:
    - `vm-manager/internal/infra/console.go:10`
- 영향
  - 서로 다른 인스턴스가 동일 포트를 점유하려 시도하여 콘솔 실패/오작동 가능
- 권장
  - 중앙 포트 할당 테이블 + 유니크 제약
  - 또는 vm-manager가 실제 할당 포트를 authoritative하게 저장/반환하고 API가 그 값을 사용

## High 2: 비활성 tenant 사용자의 콘솔 티켓 발급 가능성

- 문제
  - 일반 mutation 경로는 tenant 활성 상태를 검증하지만, 콘솔 티켓 발급 경로는 해당 검증이 없습니다.
- 근거
  - 검증 사용 예:
    - `main-api/app/api/routes.py:171`
  - 콘솔 티켓 발급:
    - `main-api/app/api/routes.py:425`
- 영향
  - tenant 비활성화 정책의 일관성 저하
- 권장
  - `issue_console_ticket()`에도 tenant active 검증 추가

## 참고

- 티켓 단일 사용/TTL 자체는 구현이 깔끔함
  - `main-api/app/adapters/console_ticket_store.py:39`
