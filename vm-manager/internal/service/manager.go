package service

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"github.com/google/uuid"

	"vm-manager/internal/config"
	"vm-manager/internal/infra"
	"vm-manager/internal/model"
	"vm-manager/internal/util"
)

type Manager struct {
	cfg       config.Config
	store     *infra.StateStore
	network   *infra.NetworkManager
	cloudInit *infra.CloudInitBuilder
	qemu      *infra.QemuManager
}

func NewManager(cfg config.Config) *Manager {
	runner := util.Runner{Timeout: cfg.CommandTimeout}
	return &Manager{
		cfg:       cfg,
		store:     infra.NewStateStore(cfg.VMBaseDir),
		network:   infra.NewNetworkManager(runner),
		cloudInit: infra.NewCloudInitBuilder(runner),
		qemu:      infra.NewQemuManager(runner),
	}
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

	baseImage, err := m.qemu.EnsureBaseImage(m.cfg.VMBaseDir, m.cfg.BaseImageURL)
	if err != nil {
		resp := failure(correlationID, "QEMU_ERROR", err.Error())
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
	if err := m.qemu.Start(payload.InstanceID, payload.CPU, payload.MemoryMiB, diskPath, seedISO, netSpec, pidFile, monitor); err != nil {
		resp := failure(correlationID, "QEMU_ERROR", err.Error())
		return resp, err
	}

	st := infra.InstanceState{
		InstanceID: payload.InstanceID,
		Name:       valueOrEmpty(payload.Name),
		CPU:        payload.CPU,
		MemoryMiB:  payload.MemoryMiB,
		DiskGiB:    payload.DiskGiB,
		Status:     "running",
		IPAddress:  netSpec.VMIP,
		HostIP:     netSpec.HostIP,
		TapIf:      netSpec.TapIf,
		BridgeIf:   netSpec.BridgeIf,
		VethHostIf: netSpec.VethHost,
		VethBrIf:   netSpec.VethBr,
		DiskPath:   diskPath,
		SeedISO:    seedISO,
		PidFile:    pidFile,
		Monitor:    monitor,
	}
	if err := m.store.SaveInstance(st); err != nil {
		resp := failure(correlationID, "QEMU_ERROR", err.Error())
		return resp, err
	}

	return model.CommandResponse{
		CorrelationID: correlationID,
		Success:       true,
		Result: map[string]any{
			"ip_address": netSpec.VMIP,
			"status":     "running",
			"host_ip":    netSpec.HostIP,
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
		VethHost: st.VethHostIf,
		VethBr:   st.VethBrIf,
		HostIP:   st.HostIP,
		VMIP:     st.IPAddress,
	}
	if err := m.network.Ensure(netSpec); err != nil {
		resp := failure(correlationID, "NETWORK_ERROR", err.Error())
		return resp, err
	}
	if err := m.qemu.Start(payload.InstanceID, payload.CPU, payload.MemoryMiB, st.DiskPath, st.SeedISO, netSpec, st.PidFile, st.Monitor); err != nil {
		resp := failure(correlationID, "QEMU_ERROR", err.Error())
		return resp, err
	}

	st.CPU = payload.CPU
	st.MemoryMiB = payload.MemoryMiB
	st.DiskGiB = payload.DiskGiB
	st.Status = "running"
	if err := m.store.SaveInstance(st); err != nil {
		resp := failure(correlationID, "QEMU_ERROR", err.Error())
		return resp, err
	}

	return model.CommandResponse{
		CorrelationID: correlationID,
		Success:       true,
		Result: map[string]any{
			"status":     "running",
			"ip_address": st.IPAddress,
		},
	}, nil
}

func (m *Manager) deleteVM(correlationID string, payload model.DeletePayload) (model.CommandResponse, error) {
	st, err := m.store.LoadInstance(payload.InstanceID)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
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
		VethHost: st.VethHostIf,
		VethBr:   st.VethBrIf,
	}
	if err := m.network.Delete(netSpec); err != nil {
		resp := failure(correlationID, "NETWORK_ERROR", err.Error())
		return resp, err
	}

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
