from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.errors import DomainError

ERROR_STATUS_MAPPING = {
    "VALIDATION_ERROR": 400,
    "CAPACITY_EXCEEDED": 409,
    "QUOTA_EXCEEDED": 409,
    "QUOTA_CONFLICT": 409,
    "TENANT_INACTIVE": 403,
    "VM_NOT_FOUND": 404,
    "INSTANCE_NOT_FOUND": 404,
    "TASK_NOT_FOUND": 404,
    "TENANT_NOT_FOUND": 404,
    "USER_NOT_FOUND": 404,
    "AUDIT_LOG_NOT_FOUND": 404,
    "CONFLICT": 409,
    "QEMU_ERROR": 502,
    "TIMEOUT": 504,
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    def handle_domain_error(_: Request, exc: DomainError):
        return JSONResponse(
            status_code=ERROR_STATUS_MAPPING.get(exc.code, 500),
            content={"code": exc.code, "message": str(exc)},
        )
