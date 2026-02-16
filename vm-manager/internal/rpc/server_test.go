package rpc

import (
	"testing"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"
)

func TestAwaitPublishConfirmAck(t *testing.T) {
	confirmCh := make(chan amqp.Confirmation, 1)
	confirmCh <- amqp.Confirmation{Ack: true}

	if err := awaitPublishConfirm(confirmCh, 100*time.Millisecond); err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
}

func TestAwaitPublishConfirmNack(t *testing.T) {
	confirmCh := make(chan amqp.Confirmation, 1)
	confirmCh <- amqp.Confirmation{Ack: false}

	if err := awaitPublishConfirm(confirmCh, 100*time.Millisecond); err == nil {
		t.Fatalf("expected error on nack confirm")
	}
}

func TestAwaitPublishConfirmTimeout(t *testing.T) {
	confirmCh := make(chan amqp.Confirmation)

	if err := awaitPublishConfirm(confirmCh, 20*time.Millisecond); err == nil {
		t.Fatalf("expected timeout error")
	}
}

