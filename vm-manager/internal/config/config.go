package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"time"
)

type Config struct {
	RabbitMQURL            string
	Concurrency            int
	BaseImageURL           string
	VMBaseDir              string
	EgressInterface        string
	CommandTimeout         time.Duration
	OperationRetryCount    int
	NetworkCleanupInterval time.Duration
}

func Load() (Config, error) {
	cfg := Config{
		RabbitMQURL:            getEnv("RABBITMQ_URL", "amqp://cloud:cloud@localhost:5672/"),
		BaseImageURL:           getEnv("BASE_IMAGE_URL", "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"),
		VMBaseDir:              getEnv("VM_BASE_DIR", "/var/lib/vm-manager"),
		EgressInterface:        getEnv("VM_EGRESS_INTERFACE", ""),
		Concurrency:            getEnvInt("VM_MANAGER_CONCURRENCY", 4),
		CommandTimeout:         time.Duration(getEnvInt("VM_COMMAND_TIMEOUT_SECONDS", 120)) * time.Second,
		OperationRetryCount:    getEnvInt("VM_OPERATION_RETRY_COUNT", 3),
		NetworkCleanupInterval: time.Duration(getEnvInt("VM_NETWORK_CLEANUP_INTERVAL_SECONDS", 300)) * time.Second,
	}

	if cfg.Concurrency < 1 {
		return Config{}, fmt.Errorf("VM_MANAGER_CONCURRENCY must be >= 1")
	}
	if cfg.OperationRetryCount < 1 {
		return Config{}, fmt.Errorf("VM_OPERATION_RETRY_COUNT must be >= 1")
	}
	if cfg.NetworkCleanupInterval < 0 {
		return Config{}, fmt.Errorf("VM_NETWORK_CLEANUP_INTERVAL_SECONDS must be >= 0")
	}
	for _, p := range []string{cfg.VMBaseDir, filepath.Join(cfg.VMBaseDir, "instances"), filepath.Join(cfg.VMBaseDir, "images"), filepath.Join(cfg.VMBaseDir, "state")} {
		if err := os.MkdirAll(p, 0o755); err != nil {
			return Config{}, fmt.Errorf("create path %s: %w", p, err)
		}
	}
	return cfg, nil
}

func getEnv(key, defaultValue string) string {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		return v
	}
	return defaultValue
}

func getEnvInt(key string, defaultValue int) int {
	v, ok := os.LookupEnv(key)
	if !ok || v == "" {
		return defaultValue
	}
	out, err := strconv.Atoi(v)
	if err != nil {
		return defaultValue
	}
	return out
}
