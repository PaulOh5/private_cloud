from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import Settings

_IMAGE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_SUPPORTED_IMAGE_FORMATS = {"qcow2"}
_SUPPORTED_IMAGE_URL_SCHEMES = {"http", "https"}


@dataclass(frozen=True)
class VmImageEntry:
    id: str
    url: str
    sha256: str | None
    image_format: str
    description: str | None


@dataclass(frozen=True)
class VmImageCatalog:
    entries: tuple[VmImageEntry, ...]
    default_id: str


def load_vm_image_catalog(settings: Settings) -> VmImageCatalog:
    configured_catalog = bool(settings.vm_image_catalog_json.strip())
    if configured_catalog:
        try:
            raw_entries = json.loads(settings.vm_image_catalog_json)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid VM_IMAGE_CATALOG_JSON") from exc
    else:
        raw_entries = [
            {
                "id": "ubuntu-24.04",
                "url": settings.base_image_url,
                "format": "qcow2",
                "is_default": True,
            },
            {
                "id": "ubuntu-22.04",
                "url": "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img",
                "format": "qcow2",
                "is_default": False,
            },
        ]

    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError("image catalog must be a non-empty list")

    by_id: dict[str, VmImageEntry] = {}
    ordered_ids: list[str] = []
    default_candidates: list[str] = []

    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise ValueError("image catalog entry must be an object")

        image_id = str(raw.get("id", "")).strip()
        if not _IMAGE_ID_PATTERN.match(image_id):
            raise ValueError(f"invalid image id: {image_id}")
        if image_id in by_id:
            raise ValueError(f"duplicate image id: {image_id}")

        image_url = str(raw.get("url", "")).strip()
        parsed = urlparse(image_url)
        if parsed.scheme not in _SUPPORTED_IMAGE_URL_SCHEMES or not parsed.netloc:
            raise ValueError(f"invalid image url for {image_id}")

        image_format = str(raw.get("format", "qcow2")).strip().lower() or "qcow2"
        if image_format not in _SUPPORTED_IMAGE_FORMATS:
            raise ValueError(f"unsupported image format for {image_id}: {image_format}")

        sha256_value = str(raw.get("sha256", "")).strip().lower() or None
        if sha256_value is None and configured_catalog and not settings.vm_image_allow_insecure_no_checksum:
            raise ValueError(f"sha256 is required for image {image_id}")
        if sha256_value is not None and not _SHA256_PATTERN.match(sha256_value):
            raise ValueError(f"invalid sha256 for image {image_id}")

        description = str(raw.get("description", "")).strip() or None
        by_id[image_id] = VmImageEntry(
            id=image_id,
            url=image_url,
            sha256=sha256_value,
            image_format=image_format,
            description=description,
        )
        ordered_ids.append(image_id)

        is_default = raw.get("is_default", False)
        if not isinstance(is_default, bool):
            raise ValueError(f"is_default must be boolean for {image_id}")
        if is_default:
            default_candidates.append(image_id)

    default_id = settings.vm_image_default_id.strip()
    if default_id:
        if default_id not in by_id:
            raise ValueError(f"VM_IMAGE_DEFAULT_ID not found: {default_id}")
    else:
        if len(default_candidates) > 1:
            raise ValueError("multiple default images configured")
        if len(default_candidates) == 1:
            default_id = default_candidates[0]
        elif len(ordered_ids) == 1:
            default_id = ordered_ids[0]
        else:
            raise ValueError("no default image configured")

    return VmImageCatalog(entries=tuple(by_id[image_id] for image_id in ordered_ids), default_id=default_id)
