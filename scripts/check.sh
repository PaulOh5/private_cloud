#!/usr/bin/env bash
set -euo pipefail

pushd main-api >/dev/null
python3 -m compileall app
popd >/dev/null

pushd vm-manager >/dev/null
go test ./...
popd >/dev/null
