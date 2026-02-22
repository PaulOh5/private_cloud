from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import require_roles
from app.api.schemas import ListVmImagesResponse, SyncVmImagesResponse, VmImageResponse
from app.ports import VmImageSyncError

image_router = APIRouter(prefix="/images", tags=["images"])
legacy_image_router = APIRouter(prefix="/image", tags=["images"])


def _sync_images_impl(request: Request) -> SyncVmImagesResponse:
    try:
        result = request.app.state.vm_image_sync_port.sync_images()
    except VmImageSyncError as exc:
        status_code = 502
        if exc.code == "VALIDATION_ERROR":
            status_code = 400
        elif exc.code == "TIMEOUT":
            status_code = 504
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc

    return SyncVmImagesResponse.model_validate(result)


@image_router.get("", response_model=ListVmImagesResponse)
def list_images(
    request: Request,
    _=Depends(require_roles("viewer", "operator", "admin")),
):
    catalog = request.app.state.vm_image_catalog
    return ListVmImagesResponse(
        items=[
            VmImageResponse(
                id=entry.id,
                url=entry.url,
                format=entry.image_format,
                is_default=entry.id == catalog.default_id,
                has_checksum=bool(entry.sha256),
                description=entry.description,
            )
            for entry in catalog.entries
        ]
    )


@image_router.post("/sync", response_model=SyncVmImagesResponse)
def sync_images(
    request: Request,
    _=Depends(require_roles("admin")),
):
    return _sync_images_impl(request)


@legacy_image_router.post("/sync", response_model=SyncVmImagesResponse, include_in_schema=False)
def sync_images_legacy_alias(
    request: Request,
    _=Depends(require_roles("admin")),
):
    return _sync_images_impl(request)
