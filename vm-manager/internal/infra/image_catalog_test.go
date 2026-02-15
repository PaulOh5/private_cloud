package infra

import (
	"strings"
	"testing"
)

func TestNewImageCatalogFallbackFromBaseImageURL(t *testing.T) {
	catalog, err := NewImageCatalog(ImageCatalogOptions{
		BaseImageURL: "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
	})
	if err != nil {
		t.Fatalf("new image catalog should succeed: %v", err)
	}

	ref, err := catalog.Resolve(nil)
	if err != nil {
		t.Fatalf("resolve default image should succeed: %v", err)
	}
	if ref.ID != "ubuntu-24.04" {
		t.Fatalf("unexpected default image id: %s", ref.ID)
	}

	jammy := "ubuntu-22.04"
	secondaryRef, err := catalog.Resolve(&jammy)
	if err != nil {
		t.Fatalf("resolve ubuntu-22.04 should succeed: %v", err)
	}
	if secondaryRef.URL != "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img" {
		t.Fatalf("unexpected ubuntu-22.04 url: %s", secondaryRef.URL)
	}
}

func TestNewImageCatalogRequiresChecksumForConfiguredCatalog(t *testing.T) {
	_, err := NewImageCatalog(ImageCatalogOptions{
		CatalogJSON: `[
			{"id":"ubuntu-24.04","url":"https://example.com/a.qcow2","format":"qcow2","is_default":true}
		]`,
	})
	if err == nil {
		t.Fatalf("expected checksum validation error")
	}
}

func TestNewImageCatalogRejectsDuplicateIDs(t *testing.T) {
	_, err := NewImageCatalog(ImageCatalogOptions{
		CatalogJSON: `[
			{"id":"ubuntu-24.04","url":"https://example.com/a.qcow2","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","format":"qcow2","is_default":true},
			{"id":"ubuntu-24.04","url":"https://example.com/b.qcow2","sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","format":"qcow2"}
		]`,
	})
	if err == nil {
		t.Fatalf("expected duplicate id validation error")
	}
}

func TestNewImageCatalogResolvesExplicitDefault(t *testing.T) {
	catalog, err := NewImageCatalog(ImageCatalogOptions{
		CatalogJSON: `[
			{"id":"ubuntu-24.04","url":"https://example.com/a.qcow2","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","format":"qcow2"},
			{"id":"ubuntu-22.04","url":"https://example.com/b.qcow2","sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","format":"qcow2"}
		]`,
		DefaultID: "ubuntu-22.04",
	})
	if err != nil {
		t.Fatalf("new image catalog should succeed: %v", err)
	}
	ref, err := catalog.Resolve(nil)
	if err != nil {
		t.Fatalf("resolve default image should succeed: %v", err)
	}
	if ref.ID != "ubuntu-22.04" {
		t.Fatalf("expected ubuntu-22.04 default, got %s", ref.ID)
	}
}

func TestImageCatalogRejectsUnknownImageID(t *testing.T) {
	catalog, err := NewImageCatalog(ImageCatalogOptions{
		CatalogJSON: `[
			{"id":"ubuntu-24.04","url":"https://example.com/a.qcow2","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","format":"qcow2","is_default":true}
		]`,
	})
	if err != nil {
		t.Fatalf("new image catalog should succeed: %v", err)
	}

	unknown := "unknown-image"
	_, err = catalog.Resolve(&unknown)
	if err == nil {
		t.Fatalf("expected unknown image_id error")
	}
	if !strings.Contains(err.Error(), "unknown image_id") {
		t.Fatalf("unexpected error: %v", err)
	}
}
