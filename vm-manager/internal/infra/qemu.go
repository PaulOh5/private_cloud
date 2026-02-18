package infra

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"vm-manager/internal/util"
)

type QemuManager struct {
	runner     util.Runner
	imageLocks sync.Map
}

func NewQemuManager(r util.Runner) *QemuManager {
	return &QemuManager{runner: r}
}

type ImageError struct {
	Code string
	Err  error
}

func (e *ImageError) Error() string {
	if e == nil || e.Err == nil {
		return ""
	}
	return e.Err.Error()
}

func (e *ImageError) Unwrap() error {
	if e == nil {
		return nil
	}
	return e.Err
}

func (q *QemuManager) EnsureBaseImage(baseDir string, image ImageRef) (string, error) {
	if image.ID == "" {
		return "", &ImageError{Code: "VALIDATION_ERROR", Err: fmt.Errorf("image id is required")}
	}
	if image.URL == "" {
		return "", &ImageError{Code: "VALIDATION_ERROR", Err: fmt.Errorf("image url is required for %s", image.ID)}
	}
	if image.Format != "qcow2" {
		return "", &ImageError{Code: "VALIDATION_ERROR", Err: fmt.Errorf("unsupported image format %q", image.Format)}
	}

	contentKey := imageContentKey(image)
	imagesDir := filepath.Join(baseDir, "images", image.ID, contentKey)
	if err := os.MkdirAll(imagesDir, 0o755); err != nil {
		return "", &ImageError{Code: "IMAGE_DOWNLOAD_ERROR", Err: err}
	}
	basePath := filepath.Join(imagesDir, "base."+image.Format)
	tmpPath := basePath + ".part"

	lock := q.imageLock(image.ID + ":" + contentKey)
	lock.Lock()
	defer lock.Unlock()

	if _, err := os.Stat(basePath); err == nil {
		if err := verifySHA256(basePath, image.SHA256); err == nil {
			return basePath, nil
		}
		_ = os.Remove(basePath)
	} else if !os.IsNotExist(err) {
		return "", &ImageError{Code: "IMAGE_DOWNLOAD_ERROR", Err: err}
	}

	_ = os.Remove(tmpPath)
	if err := q.runner.Run("curl", "-fL", "-o", tmpPath, image.URL); err != nil {
		return "", &ImageError{Code: "IMAGE_DOWNLOAD_ERROR", Err: err}
	}
	if err := verifySHA256(tmpPath, image.SHA256); err != nil {
		_ = os.Remove(tmpPath)
		return "", &ImageError{Code: "IMAGE_INTEGRITY_ERROR", Err: err}
	}
	if err := os.Rename(tmpPath, basePath); err != nil {
		_ = os.Remove(tmpPath)
		return "", &ImageError{Code: "IMAGE_DOWNLOAD_ERROR", Err: err}
	}
	return basePath, nil
}

func (q *QemuManager) imageLock(key string) *sync.Mutex {
	if v, ok := q.imageLocks.Load(key); ok {
		return v.(*sync.Mutex)
	}
	mu := &sync.Mutex{}
	v, _ := q.imageLocks.LoadOrStore(key, mu)
	return v.(*sync.Mutex)
}

func imageContentKey(image ImageRef) string {
	if len(image.SHA256) >= 16 {
		return strings.ToLower(image.SHA256[:16])
	}
	sum := sha256.Sum256([]byte(image.URL))
	return hex.EncodeToString(sum[:])[:16]
}

func verifySHA256(path string, expected string) error {
	want := strings.TrimSpace(strings.ToLower(expected))
	if want == "" {
		return nil
	}

	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()

	hash := sha256.New()
	if _, err := io.Copy(hash, f); err != nil {
		return err
	}
	got := hex.EncodeToString(hash.Sum(nil))
	if got != want {
		return fmt.Errorf("sha256 mismatch: expected %s got %s", want, got)
	}
	return nil
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
	pidStr, err := q.readPID(pidFile)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	if pidStr == "" {
		return nil
	}
	if !q.processExists(pidStr) {
		_ = os.Remove(pidFile)
		return nil
	}
	if err := q.runner.Run("sh", "-lc", "kill -TERM "+pidStr); err != nil {
		if strings.Contains(err.Error(), "No such process") || errors.Is(err, os.ErrProcessDone) {
			_ = os.Remove(pidFile)
			return nil
		}
		return err
	}
	if !q.waitForExit(pidStr, 6*time.Second) {
		_ = q.runner.Run("sh", "-lc", "kill -KILL "+pidStr)
	}
	_ = os.Remove(pidFile)
	return nil
}

func (q *QemuManager) Powerdown(monitorSocket, pidFile string, gracefulTimeout, forceTimeout time.Duration) error {
	pidStr, err := q.readPID(pidFile)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	if pidStr == "" {
		return nil
	}
	if !q.processExists(pidStr) {
		_ = os.Remove(pidFile)
		return nil
	}

	_ = q.sendMonitorPowerdown(monitorSocket)
	if q.waitForExit(pidStr, gracefulTimeout) {
		_ = os.Remove(pidFile)
		return nil
	}

	if err := q.runner.Run("sh", "-lc", "kill -TERM "+pidStr); err != nil {
		if strings.Contains(err.Error(), "No such process") || errors.Is(err, os.ErrProcessDone) {
			_ = os.Remove(pidFile)
			return nil
		}
		return err
	}
	if q.waitForExit(pidStr, forceTimeout) {
		_ = os.Remove(pidFile)
		return nil
	}
	if err := q.runner.Run("sh", "-lc", "kill -KILL "+pidStr); err != nil {
		if strings.Contains(err.Error(), "No such process") || errors.Is(err, os.ErrProcessDone) {
			_ = os.Remove(pidFile)
			return nil
		}
		return err
	}
	_ = q.waitForExit(pidStr, 2*time.Second)
	_ = os.Remove(pidFile)
	return nil
}

func (q *QemuManager) readPID(pidFile string) (string, error) {
	pidBytes, err := os.ReadFile(pidFile)
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(pidBytes)), nil
}

func (q *QemuManager) processExists(pid string) bool {
	_, err := os.Stat("/proc/" + pid)
	return err == nil
}

func (q *QemuManager) waitForExit(pid string, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for {
		if !q.processExists(pid) {
			return true
		}
		if time.Now().After(deadline) {
			return false
		}
		time.Sleep(300 * time.Millisecond)
	}
}

func (q *QemuManager) sendMonitorPowerdown(monitorSocket string) error {
	if strings.TrimSpace(monitorSocket) == "" {
		return nil
	}
	conn, err := net.DialTimeout("unix", monitorSocket, 2*time.Second)
	if err != nil {
		return err
	}
	defer conn.Close()

	_ = conn.SetWriteDeadline(time.Now().Add(2 * time.Second))
	if _, err := conn.Write([]byte("system_powerdown\n")); err != nil {
		return err
	}
	return nil
}
