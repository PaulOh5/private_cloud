package infra

import (
	"os"
	"path/filepath"
	"strings"
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
