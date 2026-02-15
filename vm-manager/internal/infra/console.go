package infra

import "hash/fnv"

const (
	DefaultConsoleVNCPortBase = 20000
	DefaultConsoleVNCPortSpan = 40000
)

func ComputeConsoleVNCPort(instanceID string, base, span int) int {
	if span <= 0 {
		span = DefaultConsoleVNCPortSpan
	}
	if base <= 0 {
		base = DefaultConsoleVNCPortBase
	}
	h := fnv.New32a()
	_, _ = h.Write([]byte(instanceID))
	return base + int(h.Sum32()%uint32(span))
}
