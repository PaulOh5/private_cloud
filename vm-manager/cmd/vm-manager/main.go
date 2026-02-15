package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"

	"vm-manager/internal/config"
	"vm-manager/internal/rpc"
	"vm-manager/internal/service"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("load config: %v", err)
	}

	manager, err := service.NewManager(cfg)
	if err != nil {
		log.Fatalf("create manager: %v", err)
	}
	server, err := rpc.New(cfg.RabbitMQURL, manager, cfg.Concurrency)
	if err != nil {
		log.Fatalf("create rpc server: %v", err)
	}
	defer server.Close()

	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	manager.StartNetworkJanitor(ctx)

	log.Printf("vm-manager started with concurrency=%d", cfg.Concurrency)
	if err := server.Run(ctx); err != nil && err != context.Canceled {
		log.Fatalf("server stopped: %v", err)
	}
}
