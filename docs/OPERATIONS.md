# Operations Notes (PoC)

## Host prerequisites
- Linux host with KVM support
- `iproute2`, `qemu-system-x86_64`, `qemu-img`, `cloud-localds`, `curl`
- Privileged execution for `vm-manager`

## Security warnings
- This MVP intentionally sets VM root password to `1234` via cloud-init.
- This must never be used in production.
- Replace with SSH keys + secret management before real deployment.

## Failure handling (Async)
- `main-api` accepts lifecycle requests asynchronously (`202 + task_id`).
- `vm-manager` publishes lifecycle results (`running/succeeded/failed`) to `vm.results`.
- `main-api` background consumer updates `instance_tasks` and `instances` state.
- Failed command messages are also published to `vm.commands.dlq`.

## Recovery notes
- Check failed tasks via `GET /tasks?status=failed`.
- Inspect DLQ (`vm.commands.dlq`) for broker-level failures.
- Re-run lifecycle operation by issuing a new API request.
