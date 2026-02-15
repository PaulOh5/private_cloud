# Frontend

React + TypeScript 운영 콘솔입니다.

## Scripts
- `npm run dev`: 개발 서버 실행
- `npm run build`: 타입체크 + 프로덕션 빌드
- `npm run test`: Vitest 실행

## API connection
- 브라우저에서 `/api/*`로 호출합니다.
- 로컬 개발(`npm run dev`) 시에는 Vite 프록시가 없으므로 `docker compose` 기반 실행을 권장합니다.
- 컨테이너 실행 시 Nginx가 `/api`를 `main-api:8000`으로 프록시합니다.
