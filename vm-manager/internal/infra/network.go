package infra

import (
	"fmt"
	"hash/fnv"
	"strconv"

	"vm-manager/internal/util"
)

type NetworkSpec struct {
	TapIf    string
	BridgeIf string
	VethHost string
	VethBr   string
	HostIP   string
	VMIP     string
	CIDR     string
}

type NetworkManager struct {
	runner util.Runner
}

func NewNetworkManager(r util.Runner) *NetworkManager {
	return &NetworkManager{runner: r}
}

func BuildNetworkSpec(instanceID string) NetworkSpec {
	short := instanceID
	if len(short) > 8 {
		short = short[:8]
	}
	subnetID := subnetFromID(instanceID)
	base := fmt.Sprintf("172.30.%d", subnetID)
	return NetworkSpec{
		TapIf:    "tap-" + short,
		BridgeIf: "br-" + short,
		VethHost: "vethh-" + short,
		VethBr:   "vethb-" + short,
		HostIP:   base + ".1",
		VMIP:     base + ".10",
		CIDR:     base + ".0/24",
	}
}

func subnetFromID(instanceID string) int {
	h := fnv.New32a()
	_, _ = h.Write([]byte(instanceID))
	v := int(h.Sum32()%250) + 1
	return v
}

func (n *NetworkManager) Ensure(spec NetworkSpec) error {
	_ = n.runner.Run("ip", "link", "del", spec.BridgeIf)
	_ = n.runner.Run("ip", "link", "del", spec.VethHost)
	_ = n.runner.Run("ip", "link", "del", spec.TapIf)

	if err := n.runner.Run("ip", "link", "add", spec.BridgeIf, "type", "bridge"); err != nil {
		return err
	}
	if err := n.runner.Run("ip", "link", "add", spec.VethHost, "type", "veth", "peer", "name", spec.VethBr); err != nil {
		return err
	}
	if err := n.runner.Run("ip", "tuntap", "add", "dev", spec.TapIf, "mode", "tap"); err != nil {
		return err
	}
	if err := n.runner.Run("ip", "link", "set", spec.VethBr, "master", spec.BridgeIf); err != nil {
		return err
	}
	if err := n.runner.Run("ip", "link", "set", spec.TapIf, "master", spec.BridgeIf); err != nil {
		return err
	}
	if err := n.runner.Run("ip", "addr", "add", spec.HostIP+"/24", "dev", spec.VethHost); err != nil {
		return err
	}
	for _, dev := range []string{spec.BridgeIf, spec.VethHost, spec.VethBr, spec.TapIf} {
		if err := n.runner.Run("ip", "link", "set", dev, "up"); err != nil {
			return err
		}
	}
	return nil
}

func (n *NetworkManager) Delete(spec NetworkSpec) error {
	for _, dev := range []string{spec.BridgeIf, spec.VethHost, spec.TapIf} {
		_ = n.runner.Run("ip", "link", "del", dev)
	}
	return nil
}

func (n *NetworkManager) ParseSubnetMask(spec NetworkSpec) string {
	return spec.HostIP + "/24"
}

func (n *NetworkManager) Gateway(spec NetworkSpec) string {
	return spec.HostIP
}

func (n *NetworkManager) CIDRPrefix(spec NetworkSpec) string {
	_, prefix, _ := splitCIDR(spec.CIDR)
	return prefix
}

func splitCIDR(cidr string) (string, string, error) {
	for i := 0; i < len(cidr); i++ {
		if cidr[i] == '/' {
			return cidr[:i], cidr[i+1:], nil
		}
	}
	return "", "", fmt.Errorf("invalid cidr: %s", cidr)
}

func PrefixInt(cidr string) int {
	_, p, err := splitCIDR(cidr)
	if err != nil {
		return 24
	}
	v, err := strconv.Atoi(p)
	if err != nil {
		return 24
	}
	return v
}
