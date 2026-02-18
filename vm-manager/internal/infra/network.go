package infra

import (
	"fmt"
	"hash/fnv"
	"strconv"
	"strings"

	"vm-manager/internal/util"
)

const vmSubnetSupernet = "172.30.0.0/16"
const vmForwardChain = "VM_MANAGER_FORWARD"
const vmNatChain = "VM_MANAGER_NAT"
const vmRuleComment = "vm-manager"
const vmManagedBridgePattern = "br+"

type NetworkSpec struct {
	TapIf    string
	BridgeIf string
	HostIP   string
	VMIP     string
	CIDR     string
}

type NetworkManager struct {
	runner      util.Runner
	egressIface string
}

func NewNetworkManager(r util.Runner, egressIface string) *NetworkManager {
	return &NetworkManager{
		runner:      r,
		egressIface: strings.TrimSpace(egressIface),
	}
}

func BuildNetworkSpec(instanceID string) NetworkSpec {
	short := shortInstanceID(instanceID)
	subnetID := subnetFromID(instanceID)
	base := fmt.Sprintf("172.30.%d", subnetID)
	return NetworkSpec{
		TapIf:    "tap-" + short,
		BridgeIf: "br-" + short,
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

func shortInstanceID(instanceID string) string {
	short := instanceID
	if len(short) > 8 {
		short = short[:8]
	}
	return short
}

func managedInterfaceSuffix(ifName string) (string, bool) {
	for _, prefix := range []string{"br-", "tap-"} {
		if strings.HasPrefix(ifName, prefix) && len(ifName) > len(prefix) {
			suffix := ifName[len(prefix):]
			if isManagedSuffixFormat(suffix) {
				return suffix, true
			}
			return "", false
		}
	}
	return "", false
}

func isManagedSuffixFormat(suffix string) bool {
	if len(suffix) != 8 {
		return false
	}
	for _, ch := range suffix {
		if (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f') || (ch >= 'A' && ch <= 'F') {
			continue
		}
		return false
	}
	return true
}

func parseManagedSuffixes(ipLinkOutput string) map[string]struct{} {
	suffixes := map[string]struct{}{}
	for _, line := range strings.Split(ipLinkOutput, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		rawName := strings.TrimSuffix(fields[1], ":")
		ifName := strings.SplitN(rawName, "@", 2)[0]
		if suffix, ok := managedInterfaceSuffix(ifName); ok {
			suffixes[suffix] = struct{}{}
		}
	}
	return suffixes
}

func (n *NetworkManager) ListManagedSuffixes() (map[string]struct{}, error) {
	out, _, err := n.runner.RunOutput("ip", "-o", "link", "show")
	if err != nil {
		return nil, err
	}
	return parseManagedSuffixes(out), nil
}

func (n *NetworkManager) CleanupBySuffix(suffix string) error {
	if !isManagedSuffixFormat(suffix) {
		return nil
	}
	spec := NetworkSpec{
		TapIf:    "tap-" + suffix,
		BridgeIf: "br-" + suffix,
	}
	return n.Delete(spec)
}

func (n *NetworkManager) CleanupByInstanceID(instanceID string) error {
	return n.CleanupBySuffix(shortInstanceID(instanceID))
}

func (n *NetworkManager) Ensure(spec NetworkSpec) error {
	_ = n.runner.Run("ip", "link", "del", spec.BridgeIf)
	_ = n.runner.Run("ip", "link", "del", spec.TapIf)

	if err := n.runner.Run("ip", "link", "add", spec.BridgeIf, "type", "bridge"); err != nil {
		return err
	}
	if err := n.runner.Run("ip", "tuntap", "add", "dev", spec.TapIf, "mode", "tap"); err != nil {
		return err
	}
	if err := n.runner.Run("ip", "link", "set", spec.TapIf, "master", spec.BridgeIf); err != nil {
		return err
	}
	if err := n.runner.Run("ip", "addr", "add", spec.HostIP+"/24", "dev", spec.BridgeIf); err != nil {
		return err
	}
	for _, dev := range []string{spec.BridgeIf, spec.TapIf} {
		if err := n.runner.Run("ip", "link", "set", dev, "up"); err != nil {
			return err
		}
	}
	if err := n.ensureInternetForwarding(); err != nil {
		return err
	}
	return nil
}

func (n *NetworkManager) Delete(spec NetworkSpec) error {
	for _, dev := range []string{spec.BridgeIf, spec.TapIf} {
		if dev == "" {
			continue
		}
		_ = n.runner.Run("ip", "link", "del", dev)
	}
	return nil
}

func (n *NetworkManager) ensureInternetForwarding() error {
	if err := n.runner.Run("sh", "-lc", "echo 1 > /proc/sys/net/ipv4/ip_forward"); err != nil {
		return err
	}

	egressIface, err := n.resolveEgressInterface()
	if err != nil {
		return err
	}
	if err := n.ensureIptablesChain("filter", vmForwardChain); err != nil {
		return err
	}
	if err := n.ensureIptablesChain("nat", vmNatChain); err != nil {
		return err
	}
	if err := n.ensureIptablesRule("filter", "FORWARD", []string{"-m", "comment", "--comment", vmRuleComment, "-j", vmForwardChain}); err != nil {
		return err
	}
	if err := n.ensureIptablesRule("nat", "POSTROUTING", []string{"-m", "comment", "--comment", vmRuleComment, "-j", vmNatChain}); err != nil {
		return err
	}
	if err := n.runner.Run("iptables", "-t", "filter", "-F", vmForwardChain); err != nil {
		return err
	}
	if err := n.runner.Run("iptables", "-t", "nat", "-F", vmNatChain); err != nil {
		return err
	}

	if err := n.ensureIptablesRule("filter", vmForwardChain, []string{"-m", "comment", "--comment", vmRuleComment, "-i", vmManagedBridgePattern, "-o", egressIface, "-s", vmSubnetSupernet, "-j", "ACCEPT"}); err != nil {
		return err
	}
	if err := n.ensureIptablesRule("filter", vmForwardChain, []string{"-m", "comment", "--comment", vmRuleComment, "-i", egressIface, "-o", vmManagedBridgePattern, "-d", vmSubnetSupernet, "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", "-j", "ACCEPT"}); err != nil {
		return err
	}
	if err := n.ensureIptablesRule("nat", vmNatChain, []string{"-m", "comment", "--comment", vmRuleComment, "-s", vmSubnetSupernet, "-o", egressIface, "-j", "MASQUERADE"}); err != nil {
		return err
	}

	n.removeLegacyWideRules()
	return nil
}

func (n *NetworkManager) ensureIptablesChain(table, chain string) error {
	if err := n.runner.Run("iptables", "-t", table, "-n", "-L", chain); err == nil {
		return nil
	}
	return n.runner.Run("iptables", "-t", table, "-N", chain)
}

func (n *NetworkManager) ensureIptablesRule(table, chain string, rule []string) error {
	checkArgs := append([]string{"-t", table, "-C", chain}, rule...)
	if err := n.runner.Run("iptables", checkArgs...); err == nil {
		return nil
	}
	addArgs := append([]string{"-t", table, "-A", chain}, rule...)
	return n.runner.Run("iptables", addArgs...)
}

func (n *NetworkManager) removeLegacyWideRules() {
	n.deleteIptablesRuleIfExists("filter", "FORWARD", []string{"-s", vmSubnetSupernet, "-j", "ACCEPT"})
	n.deleteIptablesRuleIfExists("filter", "FORWARD", []string{"-d", vmSubnetSupernet, "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", "-j", "ACCEPT"})
	n.deleteIptablesRuleIfExists("nat", "POSTROUTING", []string{"-s", vmSubnetSupernet, "-j", "MASQUERADE"})
}

func (n *NetworkManager) deleteIptablesRuleIfExists(table, chain string, rule []string) {
	for i := 0; i < 8; i++ {
		args := append([]string{"-t", table, "-D", chain}, rule...)
		if err := n.runner.Run("iptables", args...); err != nil {
			return
		}
	}
}

func (n *NetworkManager) resolveEgressInterface() (string, error) {
	if n.egressIface != "" {
		return n.egressIface, nil
	}

	out, _, err := n.runner.RunOutput("ip", "-4", "route", "show", "default")
	if err != nil {
		return "", err
	}
	iface, err := parseDefaultEgressInterface(out)
	if err != nil {
		return "", err
	}
	return iface, nil
}

func parseDefaultEgressInterface(output string) (string, error) {
	for _, line := range strings.Split(output, "\n") {
		fields := strings.Fields(line)
		for i := 0; i+1 < len(fields); i++ {
			if fields[i] == "dev" {
				return fields[i+1], nil
			}
		}
	}
	return "", fmt.Errorf("default route interface not found")
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
