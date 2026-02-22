from pydantic import BaseModel


class VmImageResponse(BaseModel):
    id: str
    url: str
    format: str
    is_default: bool
    has_checksum: bool
    description: str | None = None


class ListVmImagesResponse(BaseModel):
    items: list[VmImageResponse]


class SyncVmImagesResponseItem(BaseModel):
    id: str
    path: str


class SyncVmImagesResponse(BaseModel):
    status: str
    default_image_id: str
    total_images: int
    synchronized_items: list[SyncVmImagesResponseItem]
