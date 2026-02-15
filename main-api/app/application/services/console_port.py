from __future__ import annotations


def compute_console_vnc_port(instance_id: str, base: int = 20000, span: int = 40000) -> int:
    if base <= 0:
        base = 20000
    if span <= 0:
        span = 40000

    value = 2166136261
    for byte in instance_id.encode("utf-8"):
        value ^= byte
        value = (value * 16777619) & 0xFFFFFFFF
    return base + (value % span)
