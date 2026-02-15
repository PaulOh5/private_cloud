package infra

import "testing"

func TestParseManagedSuffixesFiltersOnlyManagedNames(t *testing.T) {
	dump := `1: lo: <LOOPBACK>
4: br-b69ec55c9a46: <BROADCAST>
346: br-d8374658: <BROADCAST>
347: vethb-d8374658@vethh-d8374658: <BROADCAST>
348: vethh-d8374658@vethb-d8374658: <BROADCAST>
349: tap-d8374658: <BROADCAST>
`

	got := parseManagedSuffixes(dump)

	if len(got) != 1 {
		t.Fatalf("expected 1 managed suffix, got %d (%v)", len(got), got)
	}
	if _, ok := got["d8374658"]; !ok {
		t.Fatalf("expected suffix d8374658 to be detected, got %v", got)
	}
}

func TestManagedInterfaceSuffixRejectsNonManagedFormat(t *testing.T) {
	cases := []string{
		"br-b69ec55c9a46",
		"br-xyz",
		"vethh-1234567",
		"tap-123456789",
	}
	for _, ifName := range cases {
		if _, ok := managedInterfaceSuffix(ifName); ok {
			t.Fatalf("expected %s to be rejected", ifName)
		}
	}
}

func TestParseDefaultEgressInterface(t *testing.T) {
	out := "default via 192.168.20.254 dev eth0 proto static metric 100\n"
	iface, err := parseDefaultEgressInterface(out)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if iface != "eth0" {
		t.Fatalf("expected eth0, got %s", iface)
	}
}
