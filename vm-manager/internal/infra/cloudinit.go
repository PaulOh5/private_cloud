package infra

import (
	"fmt"
	"os"
	"path/filepath"

	"vm-manager/internal/util"
)

type CloudInitBuilder struct {
	runner util.Runner
}

func NewCloudInitBuilder(r util.Runner) *CloudInitBuilder {
	return &CloudInitBuilder{runner: r}
}

func (c *CloudInitBuilder) Build(instanceDir string, instanceID string, vmIP string, gateway string) (string, error) {
	userDataPath := filepath.Join(instanceDir, "user-data")
	metaDataPath := filepath.Join(instanceDir, "meta-data")
	networkDataPath := filepath.Join(instanceDir, "network-config")
	seedPath := filepath.Join(instanceDir, "seed.iso")

	userData := `#cloud-config
users:
  - name: root
    lock_passwd: false
    plain_text_passwd: 1234
    shell: /bin/bash
    ssh_authorized_keys: []
ssh_pwauth: true
chpasswd:
  list: |
    root:1234
  expire: false
disable_root: false
write_files:
  - path: /etc/ssh/sshd_config.d/99-root-password-login.conf
    permissions: "0644"
    owner: root:root
    content: |
      PasswordAuthentication yes
      PermitRootLogin yes
runcmd:
  - systemctl restart ssh || systemctl restart sshd || true
`
	metaData := fmt.Sprintf("instance-id: %s\nlocal-hostname: vm-%s\n", instanceID, instanceID)
	networkData := fmt.Sprintf(`version: 2
ethernets:
  ens3:
    dhcp4: false
    addresses:
      - %s/24
    routes:
      - to: default
        via: %s
    nameservers:
      addresses:
        - 1.1.1.1
    optional: true
`, vmIP, gateway)

	if err := os.WriteFile(userDataPath, []byte(userData), 0o644); err != nil {
		return "", err
	}
	if err := os.WriteFile(metaDataPath, []byte(metaData), 0o644); err != nil {
		return "", err
	}
	if err := os.WriteFile(networkDataPath, []byte(networkData), 0o644); err != nil {
		return "", err
	}

	if err := c.runner.Run("cloud-localds", "-N", networkDataPath, seedPath, userDataPath, metaDataPath); err != nil {
		return "", err
	}
	return seedPath, nil
}
