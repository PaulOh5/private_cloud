# Operations Notes (PoC)

## Host prerequisites
- Linux host with KVM support
- `iproute2`, `qemu-system-x86_64`, `qemu-img`, `cloud-localds`, `curl`
- Privileged execution for `vm-manager`
- `main-api` must reach host QEMU VNC ports (default via `host.docker.internal`)

## VM network topology notes
- `vm-manager` uses `tap + bridge` networking. The bridge (`br-<suffix>`) is the VM gateway (`172.30.x.1`).
- Forward/NAT rules are managed through dedicated chains (`VM_MANAGER_FORWARD`, `VM_MANAGER_NAT`) and match VM traffic via bridge interfaces (`br+`).

## Security warnings
- This MVP intentionally sets VM root password to `1234` via cloud-init.
- This must never be used in production.
- Replace with SSH keys + secret management before real deployment.
- Web console(noVNC) uses one-time tickets, but QEMU VNC ports are still host-exposed; apply host firewall restrictions.

## Web console operations
- Ticket issue API: `POST /instances/{id}/console-ticket` (`admin/operator` only)
- WebSocket proxy: `WS /instances/{id}/console/ws?ticket=...`
- Default ticket TTL: `300s` (`CONSOLE_TICKET_TTL_SECONDS`)
- VNC port range: `CONSOLE_VNC_PORT_BASE` + hash(`instance_id`) % `CONSOLE_VNC_PORT_SPAN`

## Failure handling (Async)
- `main-api` accepts lifecycle requests asynchronously (`202 + task_id`).
- `vm-manager` publishes lifecycle results (`running/succeeded/failed`) to `vm.results`.
- `main-api` background consumer updates `instance_tasks` and `instances` state.
- Failed command messages are also published to `vm.commands.dlq`.

## Stop/Start behavior
- `POST /instances/{id}/stop` powers off VM without deleting it.
- `POST /instances/{id}/start` boots a stopped VM and revalidates tenant quota/capacity.
- `stopped` instances release CPU/memory usage, but still reserve instance count and disk quota.

## Recovery notes
- Check failed tasks via `GET /tasks?status=failed`.
- Inspect DLQ (`vm.commands.dlq`) for broker-level failures.
- Re-run lifecycle operation by issuing a new API request.
