package service

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"vm-manager/internal/config"
	"vm-manager/internal/infra"
	"vm-manager/internal/model"
)

func TestDispatchStartAndStopCommands(t *testing.T) {
	tempDir := t.TempDir()
	prepareFakeBinaries(t, tempDir)
	prepareBaseDir(t, tempDir)

	cfg := config.Config{
		BaseImageURL:           "https://example.com/base.qcow2",
		VMBaseDir:              tempDir,
		EgressInterface:        "eth0",
		ConsoleVNCPortBase:     20000,
		ConsoleVNCPortSpan:     40000,
		CommandTimeout:         2 * time.Second,
		OperationRetryCount:    1,
		NetworkCleanupInterval: 0,
	}
	manager, err := NewManager(cfg)
	if err != nil {
		t.Fatalf("new manager: %v", err)
	}

	instanceID := "123e4567-e89b-12d3-a456-426614174000"
	state := infra.InstanceState{
		InstanceID:     instanceID,
		CPU:            2,
		MemoryMiB:      2048,
		DiskGiB:        20,
		Status:         "stopped",
		IPAddress:      "172.30.10.10",
		HostIP:         "172.30.10.1",
		ConsoleVNCPort: 21000,
		TapIf:          "tap-123e4567",
		BridgeIf:       "br-123e4567",
		DiskPath:       filepath.Join(tempDir, "instances", instanceID, "disk.qcow2"),
		SeedISO:        filepath.Join(tempDir, "instances", instanceID, "seed.iso"),
		PidFile:        filepath.Join(tempDir, "instances", instanceID, "qemu.pid"),
		Monitor:        filepath.Join(tempDir, "instances", instanceID, "qemu.monitor.sock"),
	}
	if err := manager.store.SaveInstance(state); err != nil {
		t.Fatalf("save state: %v", err)
	}

	startPayload, _ := json.Marshal(model.StartPayload{InstanceID: instanceID, HostNode: "localhost"})
	startResp, startErr := manager.dispatch(model.CommandMessage{
		CorrelationID: "start-1",
		Command:       "instance.start",
		Payload:       startPayload,
	})
	if startErr != nil || !startResp.Success {
		t.Fatalf("start dispatch failed: err=%v resp=%+v", startErr, startResp)
	}
	if got := startResp.Result["status"]; got != "running" {
		t.Fatalf("expected running, got %+v", startResp.Result)
	}

	stopPayload, _ := json.Marshal(model.StopPayload{InstanceID: instanceID, HostNode: "localhost"})
	stopResp, stopErr := manager.dispatch(model.CommandMessage{
		CorrelationID: "stop-1",
		Command:       "instance.stop",
		Payload:       stopPayload,
	})
	if stopErr != nil || !stopResp.Success {
		t.Fatalf("stop dispatch failed: err=%v resp=%+v", stopErr, stopResp)
	}
	if got := stopResp.Result["status"]; got != "stopped" {
		t.Fatalf("expected stopped, got %+v", stopResp.Result)
	}
}

func TestUpdateWithoutBootKeepsStopped(t *testing.T) {
	tempDir := t.TempDir()
	prepareFakeBinaries(t, tempDir)
	prepareBaseDir(t, tempDir)

	cfg := config.Config{
		BaseImageURL:           "https://example.com/base.qcow2",
		VMBaseDir:              tempDir,
		EgressInterface:        "eth0",
		ConsoleVNCPortBase:     20000,
		ConsoleVNCPortSpan:     40000,
		CommandTimeout:         2 * time.Second,
		OperationRetryCount:    1,
		NetworkCleanupInterval: 0,
	}
	manager, err := NewManager(cfg)
	if err != nil {
		t.Fatalf("new manager: %v", err)
	}

	instanceID := "223e4567-e89b-12d3-a456-426614174000"
	state := infra.InstanceState{
		InstanceID:     instanceID,
		CPU:            2,
		MemoryMiB:      2048,
		DiskGiB:        20,
		Status:         "stopped",
		IPAddress:      "172.30.11.10",
		HostIP:         "172.30.11.1",
		ConsoleVNCPort: 21001,
		TapIf:          "tap-223e4567",
		BridgeIf:       "br-223e4567",
		DiskPath:       filepath.Join(tempDir, "instances", instanceID, "disk.qcow2"),
		SeedISO:        filepath.Join(tempDir, "instances", instanceID, "seed.iso"),
		PidFile:        filepath.Join(tempDir, "instances", instanceID, "qemu.pid"),
		Monitor:        filepath.Join(tempDir, "instances", instanceID, "qemu.monitor.sock"),
	}
	if err := manager.store.SaveInstance(state); err != nil {
		t.Fatalf("save state: %v", err)
	}

	boot := false
	payload := model.UpdatePayload{
		InstanceID:      instanceID,
		CPU:             4,
		MemoryMiB:       4096,
		DiskGiB:         20,
		HostNode:        "localhost",
		BootAfterUpdate: &boot,
	}
	resp, err := manager.updateVM("update-1", payload)
	if err != nil || !resp.Success {
		t.Fatalf("update failed: err=%v resp=%+v", err, resp)
	}
	if got := resp.Result["status"]; got != "stopped" {
		t.Fatalf("expected stopped result, got %+v", resp.Result)
	}

	updated, err := manager.store.LoadInstance(instanceID)
	if err != nil {
		t.Fatalf("load state: %v", err)
	}
	if updated.Status != "stopped" {
		t.Fatalf("expected stopped status, got %s", updated.Status)
	}
	if updated.CPU != 4 || updated.MemoryMiB != 4096 {
		t.Fatalf("expected updated resources, got cpu=%d mem=%d", updated.CPU, updated.MemoryMiB)
	}
}

func prepareFakeBinaries(t *testing.T, dir string) {
	t.Helper()

	if err := os.WriteFile(filepath.Join(dir, "ip"), []byte("#!/bin/sh\nif [ \"$1\" = \"-4\" ]; then echo \"default via 192.168.0.1 dev eth0\"; fi\nexit 0\n"), 0o755); err != nil {
		t.Fatalf("write fake ip: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "iptables"), []byte("#!/bin/sh\nexit 0\n"), 0o755); err != nil {
		t.Fatalf("write fake iptables: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "qemu-system-x86_64"), []byte("#!/bin/sh\nexit 0\n"), 0o755); err != nil {
		t.Fatalf("write fake qemu: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "sh"), []byte("#!/bin/sh\nexit 0\n"), 0o755); err != nil {
		t.Fatalf("write fake sh: %v", err)
	}

	originalPath := os.Getenv("PATH")
	t.Setenv("PATH", dir+":"+originalPath)
}

func prepareBaseDir(t *testing.T, baseDir string) {
	t.Helper()
	for _, path := range []string{
		baseDir,
		filepath.Join(baseDir, "instances"),
		filepath.Join(baseDir, "images"),
		filepath.Join(baseDir, "state"),
	} {
		if err := os.MkdirAll(path, 0o755); err != nil {
			t.Fatalf("mkdir %s: %v", path, err)
		}
	}
}
