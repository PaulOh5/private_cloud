from app.api.routers.audit import audit_router
from app.api.routers.auth import auth_router
from app.api.routers.images import image_router, legacy_image_router
from app.api.routers.instances import instance_router
from app.api.routers.tasks import task_router
from app.api.routers.tenants import tenant_router
from app.api.routers.users import role_router, user_router

__all__ = [
    "audit_router",
    "auth_router",
    "image_router",
    "instance_router",
    "legacy_image_router",
    "role_router",
    "task_router",
    "tenant_router",
    "user_router",
]
