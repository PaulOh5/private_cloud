package util

import (
	"bytes"
	"context"
	"fmt"
	"os/exec"
	"strings"
	"time"
)

type Runner struct {
	Timeout time.Duration
}

func (r Runner) Run(name string, args ...string) error {
	_, _, err := r.RunOutput(name, args...)
	return err
}

func (r Runner) RunOutput(name string, args ...string) (string, string, error) {
	timeout := r.Timeout
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	cmd := exec.CommandContext(ctx, name, args...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	err := cmd.Run()
	out := strings.TrimSpace(stdout.String())
	errOut := strings.TrimSpace(stderr.String())
	if err != nil {
		return out, errOut, fmt.Errorf("run %s %v: %w: %s", name, args, err, errOut)
	}
	return out, errOut, nil
}
