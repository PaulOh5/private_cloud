package service

import (
	"encoding/json"
	"testing"

	"vm-manager/internal/model"
)

func TestDispatchCancelCommandSuccess(t *testing.T) {
	m := &Manager{}
	payload, err := json.Marshal(model.CancelPayload{
		InstanceID:    "123e4567-e89b-12d3-a456-426614174000",
		TargetTaskID:  "223e4567-e89b-12d3-a456-426614174000",
		TargetCommand: "update",
		Reason:        "operator request",
	})
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}

	resp, dispatchErr := m.dispatch(model.CommandMessage{
		CorrelationID: "corr-1",
		Command:       "instance.cancel",
		Payload:       payload,
	})
	if dispatchErr != nil {
		t.Fatalf("dispatch returned error: %v", dispatchErr)
	}
	if !resp.Success {
		t.Fatalf("expected success response, got %+v", resp)
	}
	if got, ok := resp.Result["status"]; !ok || got != "canceled" {
		t.Fatalf("expected canceled status in result, got %+v", resp.Result)
	}
}

func TestDispatchCancelCommandValidationError(t *testing.T) {
	m := &Manager{}
	payload, err := json.Marshal(model.CancelPayload{
		InstanceID:    "123e4567-e89b-12d3-a456-426614174000",
		TargetTaskID:  "not-a-uuid",
		TargetCommand: "reboot",
	})
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}

	resp, dispatchErr := m.dispatch(model.CommandMessage{
		CorrelationID: "corr-2",
		Command:       "instance.cancel",
		Payload:       payload,
	})
	if dispatchErr == nil {
		t.Fatalf("expected validation error")
	}
	if resp.Success {
		t.Fatalf("expected failure response, got %+v", resp)
	}
	if resp.ErrorCode != "VALIDATION_ERROR" {
		t.Fatalf("expected VALIDATION_ERROR, got %s", resp.ErrorCode)
	}
}
