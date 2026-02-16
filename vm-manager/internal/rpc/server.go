package rpc

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	amqp "github.com/rabbitmq/amqp091-go"

	"vm-manager/internal/model"
	"vm-manager/internal/service"
)

const (
	commandExchange             = "vm.commands"
	commandQueue                = "vm.commands.q"
	dlqExchange                 = "vm.commands.dlx"
	dlqQueue                    = "vm.commands.dlq"
	resultExchange              = "vm.results"
	resultRoute                 = "instance.result"
	resultPublishConfirmTimeout = 3 * time.Second
)

type Server struct {
	conn            *amqp.Connection
	consumeCh       *amqp.Channel
	resultPubCh     *amqp.Channel
	resultConfirmCh <-chan amqp.Confirmation
	resultPubMu     sync.Mutex
	manager         *service.Manager
	concurrency     int
}

func New(url string, manager *service.Manager, concurrency int) (*Server, error) {
	conn, err := amqp.Dial(url)
	if err != nil {
		return nil, err
	}
	consumeCh, err := conn.Channel()
	if err != nil {
		_ = conn.Close()
		return nil, err
	}
	resultPubCh, err := conn.Channel()
	if err != nil {
		_ = consumeCh.Close()
		_ = conn.Close()
		return nil, err
	}

	if err := declareTopology(consumeCh); err != nil {
		_ = resultPubCh.Close()
		_ = consumeCh.Close()
		_ = conn.Close()
		return nil, err
	}

	if err := consumeCh.Qos(concurrency, 0, false); err != nil {
		_ = resultPubCh.Close()
		_ = consumeCh.Close()
		_ = conn.Close()
		return nil, err
	}
	if err := resultPubCh.Confirm(false); err != nil {
		_ = resultPubCh.Close()
		_ = consumeCh.Close()
		_ = conn.Close()
		return nil, err
	}

	return &Server{
		conn:            conn,
		consumeCh:       consumeCh,
		resultPubCh:     resultPubCh,
		resultConfirmCh: resultPubCh.NotifyPublish(make(chan amqp.Confirmation, concurrency+1)),
		manager:         manager,
		concurrency:     concurrency,
	}, nil
}

func declareTopology(ch *amqp.Channel) error {
	if err := ch.ExchangeDeclare(commandExchange, "direct", true, false, false, false, nil); err != nil {
		return err
	}
	if err := ch.ExchangeDeclare(dlqExchange, "direct", true, false, false, false, nil); err != nil {
		return err
	}
	if err := ch.ExchangeDeclare(resultExchange, "direct", true, false, false, false, nil); err != nil {
		return err
	}
	if _, err := ch.QueueDeclare(commandQueue, true, false, false, false, map[string]any{
		"x-message-ttl":             int32(120000),
		"x-dead-letter-exchange":    dlqExchange,
		"x-dead-letter-routing-key": dlqQueue,
	}); err != nil {
		return err
	}
	for _, key := range []string{"instance.create", "instance.update", "instance.delete", "instance.cancel", "image.sync"} {
		if err := ch.QueueBind(commandQueue, key, commandExchange, false, nil); err != nil {
			return err
		}
	}
	if _, err := ch.QueueDeclare(dlqQueue, true, false, false, false, nil); err != nil {
		return err
	}
	if err := ch.QueueBind(dlqQueue, dlqQueue, dlqExchange, false, nil); err != nil {
		return err
	}
	return nil
}

func (s *Server) Run(ctx context.Context) error {
	deliveries, err := s.consumeCh.Consume(commandQueue, "", false, false, false, false, nil)
	if err != nil {
		return err
	}
	sem := make(chan struct{}, s.concurrency)
	var wg sync.WaitGroup

	for {
		select {
		case <-ctx.Done():
			wg.Wait()
			return ctx.Err()
		case msg, ok := <-deliveries:
			if !ok {
				wg.Wait()
				return fmt.Errorf("delivery channel closed")
			}
			sem <- struct{}{}
			wg.Add(1)
			go func(d amqp.Delivery) {
				defer func() {
					<-sem
					wg.Done()
				}()
				s.handleDelivery(d)
			}(msg)
		}
	}
}

func normalizeCommand(command string) string {
	return strings.TrimPrefix(command, "instance.")
}

func (s *Server) publishResultEventWithConfirm(event model.ResultEvent) error {
	body, err := json.Marshal(event)
	if err != nil {
		return err
	}
	s.resultPubMu.Lock()
	defer s.resultPubMu.Unlock()

	if err := s.resultPubCh.PublishWithContext(
		context.Background(),
		resultExchange,
		resultRoute,
		false,
		false,
		amqp.Publishing{
			ContentType: "application/json",
			Body:        body,
		},
	); err != nil {
		return err
	}
	return awaitPublishConfirm(s.resultConfirmCh, resultPublishConfirmTimeout)
}

func awaitPublishConfirm(confirmCh <-chan amqp.Confirmation, timeout time.Duration) error {
	timer := time.NewTimer(timeout)
	defer timer.Stop()

	select {
	case confirm, ok := <-confirmCh:
		if !ok {
			return fmt.Errorf("publisher confirm channel closed")
		}
		if !confirm.Ack {
			return fmt.Errorf("publisher confirm nack")
		}
		return nil
	case <-timer.C:
		return fmt.Errorf("publisher confirm timeout after %s", timeout)
	}
}

func nowISO() string {
	return time.Now().UTC().Format(time.RFC3339Nano)
}

func (s *Server) handleDelivery(msg amqp.Delivery) {
	var cmd model.CommandMessage
	if err := json.Unmarshal(msg.Body, &cmd); err != nil {
		log.Printf("invalid message: %v", err)
		_ = msg.Ack(false)
		return
	}
	if cmd.RequestID == "" {
		cmd.RequestID = uuid.NewString()
	}
	if cmd.TaskID == "" {
		cmd.TaskID = msg.CorrelationId
	}
	if cmd.InstanceID == "" {
		cmd.InstanceID = ""
	}
	if cmd.CorrelationID == "" {
		cmd.CorrelationID = msg.CorrelationId
	}

	publishTaskEvents := strings.HasPrefix(cmd.Command, "instance.")
	normalized := normalizeCommand(cmd.Command)
	if publishTaskEvents && normalized != "cancel" {
		runningEvent := model.ResultEvent{
			EventID:      uuid.NewString(),
			TaskID:       cmd.TaskID,
			RequestID:    cmd.RequestID,
			InstanceID:   cmd.InstanceID,
			Command:      normalized,
			Status:       "running",
			AttemptCount: 1,
			Timestamp:    nowISO(),
		}
		if err := s.publishResultEventWithConfirm(runningEvent); err != nil {
			log.Printf("failed to publish running result event: %v", err)
			_ = msg.Nack(false, true)
			return
		}
	}

	response, attemptCount := s.manager.Handle(cmd)
	if response.CorrelationID == "" {
		response.CorrelationID = msg.CorrelationId
	}

	if publishTaskEvents {
		finalStatus := "failed"
		if response.Success && normalized == "cancel" {
			finalStatus = "canceled"
		} else if response.Success {
			finalStatus = "succeeded"
		}
		finalEvent := model.ResultEvent{
			EventID:      uuid.NewString(),
			TaskID:       cmd.TaskID,
			RequestID:    cmd.RequestID,
			InstanceID:   cmd.InstanceID,
			Command:      normalized,
			Status:       finalStatus,
			ErrorCode:    response.ErrorCode,
			ErrorMessage: response.ErrorMessage,
			Result:       response.Result,
			AttemptCount: attemptCount,
			Timestamp:    nowISO(),
		}
		if err := s.publishResultEventWithConfirm(finalEvent); err != nil {
			log.Printf("failed to publish final result event: %v", err)
			_ = msg.Nack(false, true)
			return
		}
	}

	if msg.ReplyTo != "" {
		body, _ := json.Marshal(response)
		err := s.consumeCh.PublishWithContext(
			context.Background(),
			"",
			msg.ReplyTo,
			false,
			false,
			amqp.Publishing{
				ContentType:   "application/json",
				CorrelationId: msg.CorrelationId,
				Body:          body,
			},
		)
		if err != nil {
			log.Printf("failed to publish response: %v", err)
		}
	}

	if !response.Success {
		_ = s.publishDLQ(msg)
	}
	_ = msg.Ack(false)
}

func (s *Server) publishDLQ(msg amqp.Delivery) error {
	return s.consumeCh.PublishWithContext(
		context.Background(),
		dlqExchange,
		dlqQueue,
		false,
		false,
		amqp.Publishing{
			ContentType: msg.ContentType,
			Body:        msg.Body,
			Headers:     msg.Headers,
		},
	)
}

func (s *Server) Close() {
	if s.resultPubCh != nil {
		_ = s.resultPubCh.Close()
	}
	if s.consumeCh != nil {
		_ = s.consumeCh.Close()
	}
	if s.conn != nil {
		_ = s.conn.Close()
	}
}
