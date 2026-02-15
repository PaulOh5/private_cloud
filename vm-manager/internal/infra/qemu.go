package infra

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"vm-manager/internal/util"
)

type QemuManager struct {
	runner util.Runner
}

func NewQemuManager(r util.Runner) *QemuManager {
	return &QemuManager{runner: r}
}

func (q *QemuManager) EnsureBaseImage(baseDir string, baseImageURL string) (string, error) {
	imagesDir := filepath.Join(baseDir, "images")
	if err := os.MkdirAll(imagesDir, 0o755); err != nil {
		return "", err
	}
	basePath := filepath.Join(imagesDir, "noble-server-cloudimg-amd64.img")
	if _, err := os.Stat(basePath); err == nil {
		return basePath, nil
	}
	if err := q.runner.Run("curl", "-fL", "-o", basePath, baseImageURL); err != nil {
		return "", err
	}
	return basePath, nil
}

func (q *QemuManager) CreateOverlay(instanceDir, baseImagePath string, diskGiB int) (string, error) {
	diskPath := filepath.Join(instanceDir, "disk.qcow2")
	if err := q.runner.Run("qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", baseImagePath, diskPath); err != nil {
		return "", err
	}
	if err := q.runner.Run("qemu-img", "resize", diskPath, fmt.Sprintf("%dG", diskGiB)); err != nil {
		return "", err
	}
	return diskPath, nil
}

func (q *QemuManager) ResizeDisk(diskPath string, diskGiB int) error {
	return q.runner.Run("qemu-img", "resize", diskPath, fmt.Sprintf("%dG", diskGiB))
}

func (q *QemuManager) Start(instanceID string, cpu, memoryMiB int, diskPath, seedISO string, network NetworkSpec, pidFile, monitorSocket string, vncPort int) error {
	serialLog := filepath.Join(filepath.Dir(pidFile), "serial.log")
	vncDisplay := strconv.Itoa(vncPort - 5900)
	args := []string{
		"-name", "vm-" + instanceID,
		"-enable-kvm",
		"-m", strconv.Itoa(memoryMiB),
		"-smp", strconv.Itoa(cpu),
		"-drive", "file=" + diskPath + ",if=virtio",
		"-cdrom", seedISO,
		"-netdev", "tap,id=net0,ifname=" + network.TapIf + ",script=no,downscript=no",
		"-device", "virtio-net-pci,netdev=net0",
		"-display", "none",
		"-vnc", "0.0.0.0:" + vncDisplay,
		"-serial", "file:" + serialLog,
		"-daemonize",
		"-pidfile", pidFile,
		"-monitor", "unix:" + monitorSocket + ",server,nowait",
	}
	return q.runner.Run("qemu-system-x86_64", args...)
}

func (q *QemuManager) Stop(pidFile string) error {
	pidBytes, err := os.ReadFile(pidFile)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	pidStr := strings.TrimSpace(string(pidBytes))
	if pidStr == "" {
		return nil
	}
	if _, err := os.Stat("/proc/" + pidStr); os.IsNotExist(err) {
		_ = os.Remove(pidFile)
		return nil
	}
	if err := q.runner.Run("sh", "-lc", "kill -TERM "+pidStr); err != nil {
		if strings.Contains(err.Error(), "No such process") {
			_ = os.Remove(pidFile)
			return nil
		}
		return err
	}
	for i := 0; i < 20; i++ {
		if _, err := os.Stat("/proc/" + pidStr); os.IsNotExist(err) {
			break
		}
		time.Sleep(300 * time.Millisecond)
	}
	_ = os.Remove(pidFile)
	return nil
}
