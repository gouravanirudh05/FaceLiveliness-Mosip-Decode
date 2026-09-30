#!/usr/bin/env bash
# Regenerate the Python gRPC stubs from proto/active_liveness.proto.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m grpc_tools.protoc \
  -Iactive_liveness/grpc_gen=proto \
  --python_out=src --pyi_out=src --grpc_python_out=src \
  active_liveness/grpc_gen/active_liveness.proto
touch src/active_liveness/grpc_gen/__init__.py
