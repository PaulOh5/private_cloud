package infra

import (
	"encoding/json"
	"fmt"
	"net/url"
	"regexp"
	"strings"
)

var imageIDPattern = regexp.MustCompile(`^[a-z0-9][a-z0-9._-]{0,63}$`)

type ImageRef struct {
	ID     string
	URL    string
	SHA256 string
	Format string
}

type ImageCatalogOptions struct {
	CatalogJSON             string
	DefaultID               string
	BaseImageURL            string
	AllowInsecureNoChecksum bool
}

type ImageCatalog struct {
	entries   map[string]ImageRef
	ordered   []ImageRef
	defaultID string
}

type imageCatalogEntryRaw struct {
	ID          string `json:"id"`
	URL         string `json:"url"`
	SHA256      string `json:"sha256"`
	Format      string `json:"format"`
	IsDefault   bool   `json:"is_default"`
	Description string `json:"description"`
}

func NewImageCatalog(opts ImageCatalogOptions) (*ImageCatalog, error) {
	entries := make([]imageCatalogEntryRaw, 0)
	catalogConfigured := strings.TrimSpace(opts.CatalogJSON) != ""
	if !catalogConfigured {
		entries = append(entries,
			imageCatalogEntryRaw{
				ID:        "ubuntu-24.04",
				URL:       opts.BaseImageURL,
				Format:    "qcow2",
				IsDefault: true,
			},
			imageCatalogEntryRaw{
				ID:        "ubuntu-22.04",
				URL:       "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img",
				Format:    "qcow2",
				IsDefault: false,
			},
		)
	} else if err := json.Unmarshal([]byte(opts.CatalogJSON), &entries); err != nil {
		return nil, fmt.Errorf("invalid VM_IMAGE_CATALOG_JSON: %w", err)
	}

	if len(entries) == 0 {
		return nil, fmt.Errorf("image catalog must contain at least one entry")
	}

	parsed := make(map[string]ImageRef, len(entries))
	ordered := make([]ImageRef, 0, len(entries))
	defaultCandidates := make([]string, 0, len(entries))

	for _, entry := range entries {
		id := strings.TrimSpace(entry.ID)
		if !imageIDPattern.MatchString(id) {
			return nil, fmt.Errorf("invalid image id %q", id)
		}
		if _, exists := parsed[id]; exists {
			return nil, fmt.Errorf("duplicate image id %q", id)
		}
		rawURL := strings.TrimSpace(entry.URL)
		parsedURL, err := url.Parse(rawURL)
		if err != nil || parsedURL.Scheme == "" || parsedURL.Host == "" {
			return nil, fmt.Errorf("invalid image url for %q", id)
		}
		if parsedURL.Scheme != "http" && parsedURL.Scheme != "https" {
			return nil, fmt.Errorf("unsupported url scheme for %q: %s", id, parsedURL.Scheme)
		}

		format := strings.ToLower(strings.TrimSpace(entry.Format))
		if format == "" {
			format = "qcow2"
		}
		if format != "qcow2" {
			return nil, fmt.Errorf("unsupported image format for %q: %s", id, format)
		}

		sum := strings.ToLower(strings.TrimSpace(entry.SHA256))
		if sum == "" && catalogConfigured && !opts.AllowInsecureNoChecksum {
			return nil, fmt.Errorf("sha256 is required for image %q", id)
		}
		if sum != "" && !isHexSHA256(sum) {
			return nil, fmt.Errorf("invalid sha256 for image %q", id)
		}

		ref := ImageRef{
			ID:     id,
			URL:    rawURL,
			SHA256: sum,
			Format: format,
		}
		parsed[id] = ref
		ordered = append(ordered, ref)
		if entry.IsDefault {
			defaultCandidates = append(defaultCandidates, id)
		}
	}

	defaultID := strings.TrimSpace(opts.DefaultID)
	if defaultID != "" {
		if _, ok := parsed[defaultID]; !ok {
			return nil, fmt.Errorf("VM_IMAGE_DEFAULT_ID %q not found in catalog", defaultID)
		}
	} else {
		if len(defaultCandidates) > 1 {
			return nil, fmt.Errorf("multiple default images configured")
		}
		if len(defaultCandidates) == 1 {
			defaultID = defaultCandidates[0]
		} else if len(parsed) == 1 {
			for id := range parsed {
				defaultID = id
			}
		} else {
			return nil, fmt.Errorf("no default image configured")
		}
	}

	return &ImageCatalog{entries: parsed, ordered: ordered, defaultID: defaultID}, nil
}

func (c *ImageCatalog) Resolve(imageID *string) (ImageRef, error) {
	selected := c.defaultID
	if imageID != nil && strings.TrimSpace(*imageID) != "" {
		selected = strings.TrimSpace(*imageID)
	}
	ref, ok := c.entries[selected]
	if !ok {
		return ImageRef{}, fmt.Errorf("unknown image_id: %s", selected)
	}
	return ref, nil
}

func (c *ImageCatalog) Entries() []ImageRef {
	out := make([]ImageRef, len(c.ordered))
	copy(out, c.ordered)
	return out
}

func (c *ImageCatalog) DefaultID() string {
	return c.defaultID
}

func isHexSHA256(v string) bool {
	if len(v) != 64 {
		return false
	}
	for _, c := range v {
		if (c < '0' || c > '9') && (c < 'a' || c > 'f') {
			return false
		}
	}
	return true
}
