package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"time"

	"github.com/google/uuid"

	"vm-manager/internal/config"
	"vm-manager/internal/infra"
	"vm-manager/internal/model"
	"vm-manager/internal/util"
)

type Manager struct {
	cfg          config.Config
	imageCatalog *infra.ImageCatalog
	store        *infra.StateStore
	network      *infra.NetworkManager
	cloudInit    *infra.CloudInitBuilder
	qemu         *infra.QemuManager
}

func NewManager(cfg config.Config) (*Manager, error) {
	imageCatalog, err := infra.NewImageCatalog(infra.ImageCatalogOptions{
		CatalogJSON:             cfg.ImageCatalogJSON,
		DefaultID:               cfg.ImageDefaultID,
		BaseImageURL:            cfg.BaseImageURL,
		AllowInsecureNoChecksum: cfg.ImageAllowNoChecksum,
	})
	if err != nil {
		return nil, fmt.Errorf("invalid image catalog: %w", err)
	}
	runner := util.Runner{Timeout: cfg.CommandTimeout}
	return &Manager{
		cfg:          cfg,
		imageCatalog: imageCatalog,
		store:        infra.NewStateStore(cfg.VMBaseDir),
		network:      infra.NewNetworkManager(runner, cfg.EgressInterface),
		cloudInit:    infra.NewCloudInitBuilder(runner),
		qemu:         infra.NewQemuManager(runner),
	}, nil
}

func (m *Manager) Handle(msg model.CommandMessage) (model.CommandResponse, int) {
	if msg.RequestID == "" {
		return failure(msg.CorrelationID, "VALIDATION_ERROR", "request_id is required"), 1
	}
	if cached, ok, err := m.store.LoadRequestResult(msg.RequestID); err == nil && ok {
		cached.CorrelationID = msg.CorrelationID
		return cached, 1
	}

	var response model.CommandResponse
	var err error
	attemptCount := 1

	for attempt := 1; attempt <= m.cfg.OperationRetryCount; attempt++ {
		attemptCount = attempt
		response, err = m.dispatch(msg)
		if err == nil {
			_ = m.store.SaveRequestResult(msg.RequestID, response)
			return response, attemptCount
		}
	}

	if response.CorrelationID == "" {
		response.CorrelationID = msg.CorrelationID
	}
	if response.ErrorCode == "" {
		response.ErrorCode = "QEMU_ERROR"
	}
	if response.ErrorMessage == "" {
		response.ErrorMessage = err.Error()
	}
	response.Success = false
	_ = m.store.SaveRequestResult(msg.RequestID, response)
	return response, attemptCount
}

func (m *Manager) dispatch(msg model.CommandMessage) (model.CommandResponse, error) {
	switch msg.Command {
	case "instance.create":
		var payload model.CreatePayload
		if err := json.Unmarshal(msg.Payload, &payload); err != nil {
			return failure(msg.CorrelationID, "VALIDATION_ERROR", "invalid create payload"), err
		}
		return m.createVM(msg.CorrelationID, payload)
	case "instance.update":
		var payload model.UpdatePayload
		if err := json.Unmarshal(msg.Payload, &payload); err != nil {
			return failure(msg.CorrelationID, "VALIDATION_ERROR", "invalid update payload"), err
		}
		return m.updateVM(msg.CorrelationID, payload)
	case "instance.delete":
		var payload model.DeletePayload
		if err := json.Unmarshal(msg.Payload, &payload); err != nil {
			return failure(msg.CorrelationID, "VALIDATION_ERROR", "invalid delete payload"), err
		}
		return m.deleteVM(msg.CorrelationID, payload)
	case "instance.cancel":
		var payload model.CancelPayload
		if err := json.Unmarshal(msg.Payload, &payload); err != nil {
			return failure(msg.CorrelationID, "VALIDATION_ERROR", "invalid cancel payload"), err
		}
		return m.cancelVM(msg.CorrelationID, payload)
	case "image.sync":
		var payload model.ImageSyncPayload
		if len(msg.Payload) > 0 {
			if err := json.Unmarshal(msg.Payload, &payload); err != nil {
				return failure(msg.CorrelationID, "VALIDATION_ERROR", "invalid image sync payload"), err
			}
		}
		return m.syncImages(msg.CorrelationID, payload)
	default:
		err := fmt.Errorf("unsupported command %s", msg.Command)
		return failure(msg.CorrelationID, "VALIDATION_ERROR", err.Error()), err
	}
}

func validateResource(cpu, mem, disk int) error {
	if cpu <= 0 || mem <= 0 || disk <= 0 {
		return fmt.Errorf("invalid resource values")
	}
	return nil
}

func (m *Manager) createVM(correlationID string, payload model.CreatePayload) (model.CommandResponse, error) {
	if _, err := uuid.Parse(payload.InstanceID); err != nil {
		return failure(correlationID, "VALIDATION_ERROR", "invalid instance_id"), err
	}
	if err := validateResource(payload.CPU, payload.MemoryMiB, payload.DiskGiB); err != nil {
		return failure(correlationID, "VALIDATION_ERROR", err.Error()), err
	}

	instanceDir := filepath.Join(m.cfg.VMBaseDir, "instances", payload.InstanceID)
	if err := os.MkdirAll(instanceDir, 0o755); err != nil {
		resp := failure(correlationID, "QEMU_ERROR", err.Error())
		return resp, err
	}

	imageRef, err := m.imageCatalog.Resolve(payload.ImageID)
	if err != nil {
		resp := failure(correlationID, "VALIDATION_ERROR", err.Error())
		return resp, err
	}

	baseImage, err := m.qemu.EnsureBaseImage(m.cfg.VMBaseDir, imageRef)
	if err != nil {
		code := "QEMU_ERROR"
		var imageErr *infra.ImageError
		if errors.As(err, &imageErr) {
			code = imageErr.Code
		}
		resp := failure(correlationID, code, err.Error())
		return resp, err
	}

	netSpec := infra.BuildNetworkSpec(payload.InstanceID)
	if err := m.network.Ensure(netSpec); err != nil {
		resp := failure(correlationID, "NETWORK_ERROR", err.Error())
		return resp, err
	}

	seedISO, err := m.cloudInit.Build(instanceDir, payload.InstanceID, netSpec.VMIP, netSpec.HostIP)
	if err != nil {
		resp := failure(correlationID, "QEMU_ERROR", err.Error())
		return resp, err
	}

	diskPath, err := m.qemu.CreateOverlay(instanceDir, baseImage, payload.DiskGiB)
	if err != nil {
		resp := failure(correlationID, "QEMU_ERROR", err.Error())
		return resp, err
	}

	pidFile := filepath.Join(instanceDir, "qemu.pid")
	monitor := filepath.Join(instanceDir, "qemu.monitor.sock")
	consoleVNCPort := infra.ComputeConsoleVNCPort(payload.InstanceID, m.cfg.ConsoleVNCPortBase, m.cfg.ConsoleVNCPortSpan)
	if err := m.qemu.Start(payload.InstanceID, payload.CPU, payload.MemoryMiB, diskPath, seedISO, netSpec, pidFile, monitor, consoleVNCPort); err != nil {
		resp := failure(correlationID, "QEMU_ERROR", err.Error())
		return resp, err
	}

	st := infra.InstanceState{
		InstanceID:     payload.InstanceID,
		Name:           valueOrEmpty(payload.Name),
		CPU:            payload.CPU,
		MemoryMiB:      payload.MemoryMiB,
		DiskGiB:        payload.DiskGiB,
		Status:         "running",
		IPAddress:      netSpec.VMIP,
		HostIP:         netSpec.HostIP,
		ConsoleVNCPort: consoleVNCPort,
		TapIf:          netSpec.TapIf,
		BridgeIf:       netSpec.BridgeIf,
		DiskPath:       diskPath,
		SeedISO:        seedISO,
		PidFile:        pidFile,
		Monitor:        monitor,
	}
	if err := m.store.SaveInstance(st); err != nil {
		resp := failure(correlationID, "QEMU_ERROR", err.Error())
		return resp, err
	}

	return model.CommandResponse{
		CorrelationID: correlationID,
		Success:       true,
		Result: map[string]any{
			"ip_address":       netSpec.VMIP,
			"status":           "running",
			"host_ip":          netSpec.HostIP,
			"console_vnc_port": consoleVNCPort,
		},
	}, nil
}

func (m *Manager) updateVM(correlationID string, payload model.UpdatePayload) (model.CommandResponse, error) {
	if err := validateResource(payload.CPU, payload.MemoryMiB, payload.DiskGiB); err != nil {
		return failure(correlationID, "VALIDATION_ERROR", err.Error()), err
	}
	st, err := m.store.LoadInstance(payload.InstanceID)
	if err != nil {
		resp := failure(correlationID, "VM_NOT_FOUND", "instance state not found")
		return resp, err
	}
	if payload.DiskGiB < st.DiskGiB {
		err = fmt.Errorf("disk shrink is not supported")
		resp := failure(correlationID, "VALIDATION_ERROR", err.Error())
		return resp, err
	}

	if err := m.qemu.Stop(st.PidFile); err != nil {
		resp := failure(correlationID, "QEMU_ERROR", err.Error())
		return resp, err
	}
	if payload.DiskGiB > st.DiskGiB {
		if err := m.qemu.ResizeDisk(st.DiskPath, payload.DiskGiB); err != nil {
			resp := failure(correlationID, "QEMU_ERROR", err.Error())
			return resp, err
		}
	}

	netSpec := infra.NetworkSpec{
		TapIf:    st.TapIf,
		BridgeIf: st.BridgeIf,
		HostIP:   st.HostIP,
		VMIP:     st.IPAddress,
	}
	if err := m.network.Ensure(netSpec); err != nil {
		resp := failure(correlationID, "NETWORK_ERROR", err.Error())
		return resp, err
	}
	consoleVNCPort := st.ConsoleVNCPort
	if consoleVNCPort == 0 {
		consoleVNCPort = infra.ComputeConsoleVNCPort(payload.InstanceID, m.cfg.ConsoleVNCPortBase, m.cfg.ConsoleVNCPortSpan)
	}
	if err := m.qemu.Start(payload.InstanceID, payload.CPU, payload.MemoryMiB, st.DiskPath, st.SeedISO, netSpec, st.PidFile, st.Monitor, consoleVNCPort); err != nil {
		resp := failure(correlationID, "QEMU_ERROR", err.Error())
		return resp, err
	}

	st.CPU = payload.CPU
	st.MemoryMiB = payload.MemoryMiB
	st.DiskGiB = payload.DiskGiB
	st.Status = "running"
	st.ConsoleVNCPort = consoleVNCPort
	if err := m.store.SaveInstance(st); err != nil {
		resp := failure(correlationID, "QEMU_ERROR", err.Error())
		return resp, err
	}

	return model.CommandResponse{
		CorrelationID: correlationID,
		Success:       true,
		Result: map[string]any{
			"status":           "running",
			"ip_address":       st.IPAddress,
			"console_vnc_port": consoleVNCPort,
		},
	}, nil
}

func (m *Manager) deleteVM(correlationID string, payload model.DeletePayload) (model.CommandResponse, error) {
	st, err := m.store.LoadInstance(payload.InstanceID)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			_ = m.network.CleanupByInstanceID(payload.InstanceID)
			_ = os.RemoveAll(filepath.Join(m.cfg.VMBaseDir, "instances", payload.InstanceID))
			_ = m.store.DeleteInstance(payload.InstanceID)
			return model.CommandResponse{CorrelationID: correlationID, Success: true, Result: map[string]any{"status": "deleted"}}, nil
		}
		resp := failure(correlationID, "VM_NOT_FOUND", "instance state not found")
		return resp, err
	}

	if err := m.qemu.Stop(st.PidFile); err != nil {
		resp := failure(correlationID, "QEMU_ERROR", err.Error())
		return resp, err
	}
	netSpec := infra.NetworkSpec{
		TapIf:    st.TapIf,
		BridgeIf: st.BridgeIf,
	}
	if err := m.network.Delete(netSpec); err != nil {
		resp := failure(correlationID, "NETWORK_ERROR", err.Error())
		return resp, err
	}
	_ = m.network.CleanupByInstanceID(payload.InstanceID)

	instanceDir := filepath.Join(m.cfg.VMBaseDir, "instances", payload.InstanceID)
	if err := os.RemoveAll(instanceDir); err != nil {
		resp := failure(correlationID, "QEMU_ERROR", err.Error())
		return resp, err
	}
	if err := m.store.DeleteInstance(payload.InstanceID); err != nil {
		resp := failure(correlationID, "QEMU_ERROR", err.Error())
		return resp, err
	}

	return model.CommandResponse{CorrelationID: correlationID, Success: true, Result: map[string]any{"status": "deleted"}}, nil
}

func (m *Manager) cancelVM(correlationID string, payload model.CancelPayload) (model.CommandResponse, error) {
	if payload.TargetTaskID == "" {
		err := fmt.Errorf("target_task_id is required")
		return failure(correlationID, "VALIDATION_ERROR", err.Error()), err
	}
	if _, err := uuid.Parse(payload.TargetTaskID); err != nil {
		return failure(correlationID, "VALIDATION_ERROR", "invalid target_task_id"), err
	}
	switch payload.TargetCommand {
	case "create", "update", "delete":
	default:
		err := fmt.Errorf("invalid target_command")
		return failure(correlationID, "VALIDATION_ERROR", err.Error()), err
	}

	return model.CommandResponse{
		CorrelationID: correlationID,
		Success:       true,
		Result: map[string]any{
			"status":         "canceled",
			"target_task_id": payload.TargetTaskID,
			"target_command": payload.TargetCommand,
			"reason":         payload.Reason,
		},
	}, nil
}

func (m *Manager) syncImages(correlationID string, _ model.ImageSyncPayload) (model.CommandResponse, error) {
	entries := m.imageCatalog.Entries()
	syncedItems := make([]map[string]any, 0, len(entries))

	for _, entry := range entries {
		path, err := m.qemu.EnsureBaseImage(m.cfg.VMBaseDir, entry)
		if err != nil {
			code := "QEMU_ERROR"
			var imageErr *infra.ImageError
			if errors.As(err, &imageErr) {
				code = imageErr.Code
			}
			resp := failure(correlationID, code, fmt.Sprintf("sync image %s: %v", entry.ID, err))
			return resp, err
		}
		syncedItems = append(syncedItems, map[string]any{
			"id":   entry.ID,
			"path": path,
		})
	}

	return model.CommandResponse{
		CorrelationID: correlationID,
		Success:       true,
		Result: map[string]any{
			"status":             "synced",
			"default_image_id":   m.imageCatalog.DefaultID(),
			"total_images":       len(entries),
			"synchronized_items": syncedItems,
		},
	}, nil
}

func (m *Manager) StartNetworkJanitor(ctx context.Context) {
	interval := m.cfg.NetworkCleanupInterval
	if interval <= 0 {
		log.Printf("network janitor disabled")
		return
	}

	if err := m.CleanupStaleNetworkInterfaces(); err != nil {
		log.Printf("network janitor initial cleanup failed: %v", err)
	}

	ticker := time.NewTicker(interval)
	go func() {
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				if err := m.CleanupStaleNetworkInterfaces(); err != nil {
					log.Printf("network janitor cleanup failed: %v", err)
				}
			}
		}
	}()
	log.Printf("network janitor started with interval=%s", interval)
}

func (m *Manager) CleanupStaleNetworkInterfaces() error {
	states, err := m.store.ListInstances()
	if err != nil {
		return err
	}

	activeSuffixes := map[string]struct{}{}
	for _, st := range states {
		if suffix := shortInstanceID(st.InstanceID); suffix != "" {
			activeSuffixes[suffix] = struct{}{}
		}
	}

	managedSuffixes, err := m.network.ListManagedSuffixes()
	if err != nil {
		return err
	}

	for suffix := range managedSuffixes {
		if _, ok := activeSuffixes[suffix]; ok {
			continue
		}
		if err := m.network.CleanupBySuffix(suffix); err != nil {
			log.Printf("network janitor cleanup suffix=%s failed: %v", suffix, err)
		}
	}
	return nil
}

func shortInstanceID(instanceID string) string {
	short := instanceID
	if len(short) > 8 {
		short = short[:8]
	}
	return short
}

func failure(correlationID, code, message string) model.CommandResponse {
	return model.CommandResponse{
		CorrelationID: correlationID,
		Success:       false,
		ErrorCode:     code,
		ErrorMessage:  message,
	}
}

func valueOrEmpty(v *string) string {
	if v == nil {
		return ""
	}
	return *v
}
