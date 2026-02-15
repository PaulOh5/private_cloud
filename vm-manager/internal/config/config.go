package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	RabbitMQURL            string
	Concurrency            int
	BaseImageURL           string
	ImageCatalogJSON       string
	ImageDefaultID         string
	ImageAllowNoChecksum   bool
	VMBaseDir              string
	EgressInterface        string
	ConsoleVNCPortBase     int
	ConsoleVNCPortSpan     int
	CommandTimeout         time.Duration
	OperationRetryCount    int
	NetworkCleanupInterval time.Duration
}

func Load() (Config, error) {
	cfg := Config{
		RabbitMQURL:            getEnv("RABBITMQ_URL", "amqp://cloud:cloud@localhost:5672/"),
		BaseImageURL:           getEnv("BASE_IMAGE_URL", "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"),
		ImageCatalogJSON:       getEnv("VM_IMAGE_CATALOG_JSON", ""),
		ImageDefaultID:         getEnv("VM_IMAGE_DEFAULT_ID", ""),
		ImageAllowNoChecksum:   getEnvBool("VM_IMAGE_ALLOW_INSECURE_NO_CHECKSUM", false),
		VMBaseDir:              getEnv("VM_BASE_DIR", "/var/lib/vm-manager"),
		EgressInterface:        getEnv("VM_EGRESS_INTERFACE", ""),
		ConsoleVNCPortBase:     getEnvInt("CONSOLE_VNC_PORT_BASE", 20000),
		ConsoleVNCPortSpan:     getEnvInt("CONSOLE_VNC_PORT_SPAN", 40000),
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
	if cfg.ConsoleVNCPortBase <= 5900 {
		return Config{}, fmt.Errorf("CONSOLE_VNC_PORT_BASE must be > 5900")
	}
	if cfg.ConsoleVNCPortSpan < 1 {
		return Config{}, fmt.Errorf("CONSOLE_VNC_PORT_SPAN must be >= 1")
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

func getEnvBool(key string, defaultValue bool) bool {
	v, ok := os.LookupEnv(key)
	if !ok || strings.TrimSpace(v) == "" {
		return defaultValue
	}
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "1", "true", "yes", "on":
		return true
	case "0", "false", "no", "off":
		return false
	default:
		return defaultValue
	}
}
