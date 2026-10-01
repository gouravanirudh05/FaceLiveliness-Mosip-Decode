#!/usr/bin/env bash
# Regenerate the Python gRPC stubs from proto/passive_liveness.proto.
# The proto imports the active module's proto, which must sit at ../face-liveness-active.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m grpc_tools.protoc \
  -Ipassive_liveness/grpc_gen=proto \
  -Iactive_liveness/grpc_gen=../face-liveness-active/proto \
  --python_out=src --pyi_out=src --grpc_python_out=src \
  passive_liveness/grpc_gen/passive_liveness.proto
touch src/passive_liveness/grpc_gen/__init__.py
