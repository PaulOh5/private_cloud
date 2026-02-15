package infra

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"vm-manager/internal/model"
)

type InstanceState struct {
	InstanceID string `json:"instance_id"`
	Name       string `json:"name"`
	CPU        int    `json:"cpu"`
	MemoryMiB  int    `json:"memory_mib"`
	DiskGiB    int    `json:"disk_gib"`
	Status     string `json:"status"`
	IPAddress  string `json:"ip_address"`
	HostIP     string `json:"host_ip"`
	TapIf      string `json:"tap_if"`
	BridgeIf   string `json:"bridge_if"`
	VethHostIf string `json:"veth_host_if"`
	VethBrIf   string `json:"veth_br_if"`
	DiskPath   string `json:"disk_path"`
	SeedISO    string `json:"seed_iso"`
	PidFile    string `json:"pid_file"`
	Monitor    string `json:"monitor"`
}

type StateStore struct {
	baseDir string
	mu      sync.Mutex
}

func NewStateStore(baseDir string) *StateStore {
	return &StateStore{baseDir: baseDir}
}

func (s *StateStore) instancePath(instanceID string) string {
	return filepath.Join(s.baseDir, "state", fmt.Sprintf("instance-%s.json", instanceID))
}

func (s *StateStore) requestPath(requestID string) string {
	return filepath.Join(s.baseDir, "state", fmt.Sprintf("request-%s.json", requestID))
}

func (s *StateStore) SaveInstance(st InstanceState) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return writeJSONAtomic(s.instancePath(st.InstanceID), st)
}

func (s *StateStore) LoadInstance(instanceID string) (InstanceState, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var st InstanceState
	data, err := os.ReadFile(s.instancePath(instanceID))
	if err != nil {
		return st, err
	}
	if err := json.Unmarshal(data, &st); err != nil {
		return st, err
	}
	return st, nil
}

func (s *StateStore) DeleteInstance(instanceID string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := os.Remove(s.instancePath(instanceID)); err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}

func (s *StateStore) SaveRequestResult(requestID string, response model.CommandResponse) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return writeJSONAtomic(s.requestPath(requestID), response)
}

func (s *StateStore) LoadRequestResult(requestID string) (model.CommandResponse, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var response model.CommandResponse
	data, err := os.ReadFile(s.requestPath(requestID))
	if os.IsNotExist(err) {
		return response, false, nil
	}
	if err != nil {
		return response, false, err
	}
	if err := json.Unmarshal(data, &response); err != nil {
		return response, false, err
	}
	return response, true, nil
}

func (s *StateStore) ListInstances() ([]InstanceState, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	stateDir := filepath.Join(s.baseDir, "state")
	entries, err := os.ReadDir(stateDir)
	if os.IsNotExist(err) {
		return []InstanceState{}, nil
	}
	if err != nil {
		return nil, err
	}

	out := make([]InstanceState, 0)
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		name := entry.Name()
		if !strings.HasPrefix(name, "instance-") || !strings.HasSuffix(name, ".json") {
			continue
		}

		raw, err := os.ReadFile(filepath.Join(stateDir, name))
		if err != nil {
			return nil, err
		}
		var st InstanceState
		if err := json.Unmarshal(raw, &st); err != nil {
			return nil, err
		}
		out = append(out, st)
	}
	return out, nil
}

func writeJSONAtomic(path string, v any) error {
	data, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}
