package tests

import (
	"testing"

	"vm-manager/internal/infra"
)

func TestBuildNetworkSpecDeterministic(t *testing.T) {
	id := "123e4567-e89b-12d3-a456-426614174000"
	a := infra.BuildNetworkSpec(id)
	b := infra.BuildNetworkSpec(id)

	if a.HostIP != b.HostIP || a.VMIP != b.VMIP || a.TapIf != b.TapIf {
		t.Fatalf("expected deterministic spec, got %+v and %+v", a, b)
	}
	if a.HostIP == a.VMIP {
		t.Fatalf("expected host ip and vm ip to differ")
	}
}
