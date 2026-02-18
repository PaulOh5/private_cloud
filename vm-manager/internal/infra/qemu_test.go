package infra

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"vm-manager/internal/util"
)

func TestComputeConsoleVNCPortDeterministic(t *testing.T) {
	instanceID := "123e4567-e89b-12d3-a456-426614174000"
	a := ComputeConsoleVNCPort(instanceID, 20000, 40000)
	b := ComputeConsoleVNCPort(instanceID, 20000, 40000)

	if a != b {
		t.Fatalf("expected deterministic port, got %d and %d", a, b)
	}
	if a < 20000 || a >= 60000 {
		t.Fatalf("port out of range: %d", a)
	}
}

func TestQemuStartIncludesVNCArgument(t *testing.T) {
	tempDir := t.TempDir()
	logPath := filepath.Join(tempDir, "captured-args.log")
	launcherPath := filepath.Join(tempDir, "qemu-system-x86_64")
	script := "#!/bin/sh\nprintf '%s' \"$*\" > " + logPath + "\n"
	if err := os.WriteFile(launcherPath, []byte(script), 0o755); err != nil {
		t.Fatalf("write fake qemu binary: %v", err)
	}

	originalPath := os.Getenv("PATH")
	t.Setenv("PATH", tempDir+":"+originalPath)

	manager := NewQemuManager(util.Runner{Timeout: time.Second})
	err := manager.Start(
		"123e4567-e89b-12d3-a456-426614174000",
		2,
		2048,
		"/tmp/disk.qcow2",
		"/tmp/seed.iso",
		NetworkSpec{TapIf: "tap-test0"},
		"/tmp/qemu.pid",
		"/tmp/qemu.monitor.sock",
		20000,
	)
	if err != nil {
		t.Fatalf("start should succeed: %v", err)
	}

	raw, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("read captured args: %v", err)
	}
	args := string(raw)
	if !strings.Contains(args, "-vnc 0.0.0.0:14100") {
		t.Fatalf("expected vnc argument in %q", args)
	}
}

func TestEnsureBaseImageDownloadAndCacheHit(t *testing.T) {
	tempDir := t.TempDir()
	sourcePath := filepath.Join(tempDir, "source.qcow2")
	if err := os.WriteFile(sourcePath, []byte("image-bytes"), 0o644); err != nil {
		t.Fatalf("write source image: %v", err)
	}
	sum := sha256.Sum256([]byte("image-bytes"))
	checksum := hex.EncodeToString(sum[:])

	countPath := filepath.Join(tempDir, "curl-count.log")
	curlPath := filepath.Join(tempDir, "curl")
	script := "#!/bin/sh\nout=\"\"\nsrc=\"\"\nwhile [ \"$#\" -gt 0 ]; do\n  if [ \"$1\" = \"-o\" ]; then\n    out=\"$2\"\n    shift 2\n    continue\n  fi\n  src=\"$1\"\n  shift\n done\nif [ -n \"$FAKE_CURL_COUNT_FILE\" ]; then\n  echo x >> \"$FAKE_CURL_COUNT_FILE\"\nfi\ncp \"$src\" \"$out\"\n"
	if err := os.WriteFile(curlPath, []byte(script), 0o755); err != nil {
		t.Fatalf("write fake curl: %v", err)
	}

	originalPath := os.Getenv("PATH")
	t.Setenv("PATH", tempDir+":"+originalPath)
	t.Setenv("FAKE_CURL_COUNT_FILE", countPath)

	manager := NewQemuManager(util.Runner{Timeout: time.Second})
	ref := ImageRef{
		ID:     "ubuntu-24.04",
		URL:    sourcePath,
		SHA256: checksum,
		Format: "qcow2",
	}

	firstPath, err := manager.EnsureBaseImage(tempDir, ref)
	if err != nil {
		t.Fatalf("first ensure should succeed: %v", err)
	}
	secondPath, err := manager.EnsureBaseImage(tempDir, ref)
	if err != nil {
		t.Fatalf("second ensure should succeed: %v", err)
	}
	if firstPath != secondPath {
		t.Fatalf("expected same path for cache hit, got %s and %s", firstPath, secondPath)
	}

	raw, err := os.ReadFile(countPath)
	if err != nil {
		t.Fatalf("read curl count: %v", err)
	}
	if got := strings.Count(string(raw), "\n"); got != 1 {
		t.Fatalf("expected one download, got %d", got)
	}
}

func TestEnsureBaseImageChecksumMismatch(t *testing.T) {
	tempDir := t.TempDir()
	sourcePath := filepath.Join(tempDir, "source.qcow2")
	if err := os.WriteFile(sourcePath, []byte("image-bytes"), 0o644); err != nil {
		t.Fatalf("write source image: %v", err)
	}

	curlPath := filepath.Join(tempDir, "curl")
	script := "#!/bin/sh\nout=\"\"\nsrc=\"\"\nwhile [ \"$#\" -gt 0 ]; do\n  if [ \"$1\" = \"-o\" ]; then\n    out=\"$2\"\n    shift 2\n    continue\n  fi\n  src=\"$1\"\n  shift\n done\ncp \"$src\" \"$out\"\n"
	if err := os.WriteFile(curlPath, []byte(script), 0o755); err != nil {
		t.Fatalf("write fake curl: %v", err)
	}

	originalPath := os.Getenv("PATH")
	t.Setenv("PATH", tempDir+":"+originalPath)

	manager := NewQemuManager(util.Runner{Timeout: time.Second})
	_, err := manager.EnsureBaseImage(tempDir, ImageRef{
		ID:     "ubuntu-24.04",
		URL:    sourcePath,
		SHA256: strings.Repeat("0", 64),
		Format: "qcow2",
	})
	var imageErr *ImageError
	if !errors.As(err, &imageErr) {
		t.Fatalf("expected image error, got %v", err)
	}
	if imageErr.Code != "IMAGE_INTEGRITY_ERROR" {
		t.Fatalf("unexpected error code: %s", imageErr.Code)
	}
}

func TestEnsureBaseImageConcurrentSingleDownload(t *testing.T) {
	tempDir := t.TempDir()
	sourcePath := filepath.Join(tempDir, "source.qcow2")
	if err := os.WriteFile(sourcePath, []byte("image-bytes"), 0o644); err != nil {
		t.Fatalf("write source image: %v", err)
	}
	sum := sha256.Sum256([]byte("image-bytes"))
	checksum := hex.EncodeToString(sum[:])

	countPath := filepath.Join(tempDir, "curl-count.log")
	curlPath := filepath.Join(tempDir, "curl")
	script := "#!/bin/sh\nout=\"\"\nsrc=\"\"\nwhile [ \"$#\" -gt 0 ]; do\n  if [ \"$1\" = \"-o\" ]; then\n    out=\"$2\"\n    shift 2\n    continue\n  fi\n  src=\"$1\"\n  shift\n done\nif [ -n \"$FAKE_CURL_COUNT_FILE\" ]; then\n  echo x >> \"$FAKE_CURL_COUNT_FILE\"\nfi\ncp \"$src\" \"$out\"\n"
	if err := os.WriteFile(curlPath, []byte(script), 0o755); err != nil {
		t.Fatalf("write fake curl: %v", err)
	}

	originalPath := os.Getenv("PATH")
	t.Setenv("PATH", tempDir+":"+originalPath)
	t.Setenv("FAKE_CURL_COUNT_FILE", countPath)

	manager := NewQemuManager(util.Runner{Timeout: time.Second})
	ref := ImageRef{
		ID:     "ubuntu-24.04",
		URL:    sourcePath,
		SHA256: checksum,
		Format: "qcow2",
	}

	var wg sync.WaitGroup
	for i := 0; i < 6; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, err := manager.EnsureBaseImage(tempDir, ref); err != nil {
				t.Errorf("ensure base image failed: %v", err)
			}
		}()
	}
	wg.Wait()

	raw, err := os.ReadFile(countPath)
	if err != nil {
		t.Fatalf("read curl count: %v", err)
	}
	if got := strings.Count(string(raw), "\n"); got != 1 {
		t.Fatalf("expected one download across concurrent calls, got %d", got)
	}
}

func TestPowerdownFallsBackToTermAndKill(t *testing.T) {
	tempDir := t.TempDir()
	logPath := filepath.Join(tempDir, "kill.log")
	shPath := filepath.Join(tempDir, "sh")
	script := "#!/bin/sh\necho \"$*\" >> " + logPath + "\nexit 0\n"
	if err := os.WriteFile(shPath, []byte(script), 0o755); err != nil {
		t.Fatalf("write fake sh: %v", err)
	}
	originalPath := os.Getenv("PATH")
	t.Setenv("PATH", tempDir+":"+originalPath)

	pidFile := filepath.Join(tempDir, "qemu.pid")
	if err := os.WriteFile(pidFile, []byte(fmt.Sprintf("%d\n", os.Getpid())), 0o644); err != nil {
		t.Fatalf("write pid file: %v", err)
	}

	manager := NewQemuManager(util.Runner{Timeout: time.Second})
	if err := manager.Powerdown("", pidFile, 100*time.Millisecond, 100*time.Millisecond); err != nil {
		t.Fatalf("powerdown should succeed with fallback: %v", err)
	}

	raw, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("read kill log: %v", err)
	}
	logs := string(raw)
	if !strings.Contains(logs, "kill -TERM") {
		t.Fatalf("expected TERM fallback in logs, got %q", logs)
	}
	if !strings.Contains(logs, "kill -KILL") {
		t.Fatalf("expected KILL fallback in logs, got %q", logs)
	}
}
