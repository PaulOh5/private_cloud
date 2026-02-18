package model

import "encoding/json"

type CommandMessage struct {
	RequestID     string          `json:"request_id"`
	TaskID        string          `json:"task_id"`
	InstanceID    string          `json:"instance_id"`
	CorrelationID string          `json:"correlation_id"`
	Timestamp     string          `json:"timestamp"`
	Command       string          `json:"command"`
	Payload       json.RawMessage `json:"payload"`
}

type CreatePayload struct {
	InstanceID string  `json:"instance_id"`
	Name       *string `json:"name"`
	CPU        int     `json:"cpu"`
	MemoryMiB  int     `json:"memory_mib"`
	DiskGiB    int     `json:"disk_gib"`
	ImageID    *string `json:"image_id"`
	HostNode   string  `json:"host_node"`
}

type UpdatePayload struct {
	InstanceID      string `json:"instance_id"`
	CPU             int    `json:"cpu"`
	MemoryMiB       int    `json:"memory_mib"`
	DiskGiB         int    `json:"disk_gib"`
	HostNode        string `json:"host_node"`
	BootAfterUpdate *bool  `json:"boot_after_update"`
}

type DeletePayload struct {
	InstanceID string `json:"instance_id"`
	HostNode   string `json:"host_node"`
}

type StartPayload struct {
	InstanceID string `json:"instance_id"`
	HostNode   string `json:"host_node"`
}

type StopPayload struct {
	InstanceID string `json:"instance_id"`
	HostNode   string `json:"host_node"`
}

type CancelPayload struct {
	InstanceID    string `json:"instance_id"`
	TargetTaskID  string `json:"target_task_id"`
	TargetCommand string `json:"target_command"`
	Reason        string `json:"reason"`
}

type ImageSyncPayload struct{}

type CommandResponse struct {
	CorrelationID string         `json:"correlation_id"`
	Success       bool           `json:"success"`
	ErrorCode     string         `json:"error_code,omitempty"`
	ErrorMessage  string         `json:"error_message,omitempty"`
	Result        map[string]any `json:"result,omitempty"`
}

type ResultEvent struct {
	EventID      string         `json:"event_id"`
	TaskID       string         `json:"task_id"`
	RequestID    string         `json:"request_id"`
	InstanceID   string         `json:"instance_id"`
	Command      string         `json:"command"`
	Status       string         `json:"status"`
	ErrorCode    string         `json:"error_code,omitempty"`
	ErrorMessage string         `json:"error_message,omitempty"`
	Result       map[string]any `json:"result,omitempty"`
	AttemptCount int            `json:"attempt_count"`
	Timestamp    string         `json:"timestamp"`
}

func (r CommandResponse) Clone() CommandResponse {
	out := r
	if r.Result != nil {
		out.Result = map[string]any{}
		for k, v := range r.Result {
			out.Result[k] = v
		}
	}
	return out
}
