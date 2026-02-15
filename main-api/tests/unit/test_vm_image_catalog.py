import pytest

from app.application.services.vm_image_catalog import load_vm_image_catalog
from app.config import Settings


def test_load_vm_image_catalog_fallback_from_base_image_url():
    settings = Settings(
        base_image_url="https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
        vm_image_catalog_json="",
        vm_image_default_id="",
        vm_image_allow_insecure_no_checksum=False,
    )

    catalog = load_vm_image_catalog(settings)

    assert catalog.default_id == "ubuntu-24.04"
    assert len(catalog.entries) == 2
    assert catalog.entries[0].id == "ubuntu-24.04"
    assert catalog.entries[0].sha256 is None
    assert catalog.entries[1].id == "ubuntu-22.04"
    assert catalog.entries[1].url == "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img"


def test_load_vm_image_catalog_requires_checksum_when_catalog_configured():
    settings = Settings(
        vm_image_catalog_json='[{"id":"ubuntu-24.04","url":"https://example.com/noble.qcow2","format":"qcow2","is_default":true}]',
        vm_image_default_id="",
        vm_image_allow_insecure_no_checksum=False,
    )

    with pytest.raises(ValueError) as exc_info:
        load_vm_image_catalog(settings)
    assert "sha256 is required" in str(exc_info.value)


def test_load_vm_image_catalog_respects_default_id_override():
    settings = Settings(
        vm_image_catalog_json='['
        '{"id":"ubuntu-24.04","url":"https://example.com/noble.qcow2","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","format":"qcow2"},'
        '{"id":"ubuntu-22.04","url":"https://example.com/jammy.qcow2","sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","format":"qcow2"}'
        ']',
        vm_image_default_id="ubuntu-22.04",
        vm_image_allow_insecure_no_checksum=False,
    )

    catalog = load_vm_image_catalog(settings)

    assert catalog.default_id == "ubuntu-22.04"
    assert [entry.id for entry in catalog.entries] == ["ubuntu-24.04", "ubuntu-22.04"]
