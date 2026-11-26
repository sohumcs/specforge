#!/usr/bin/env sh
# Regenerate the pinned Linux dependency locks (amd64 + arm64 via --universal).
#
# torch is installed separately from the CPU-only wheel index (see Dockerfile),
# so it and the CUDA packages it would drag in from PyPI are excluded here.
# Run from backend/ with uv available (pip install uv).
set -eu

EXCLUDE="torch triton cuda-bindings cuda-pathfinder cuda-toolkit nvidia-cublas nvidia-cuda-cccl \
nvidia-cuda-cupti nvidia-cuda-nvrtc nvidia-cuda-runtime nvidia-cudnn-cu13 nvidia-cufft \
nvidia-cufile nvidia-cusolver nvidia-cusparse nvidia-cusparselt-cu13 nvidia-nccl-cu13 \
nvidia-nvjitlink nvidia-nvshmem-cu13 nvidia-nvtx"

ARGS="--universal --python-version 3.12 --no-header"
for p in $EXCLUDE; do ARGS="$ARGS --no-emit-package $p"; done

# shellcheck disable=SC2086
uv pip compile pyproject.toml $ARGS -o requirements.lock
# shellcheck disable=SC2086
uv pip compile pyproject.toml --extra dev $ARGS -o requirements-dev.lock
echo "locks updated"
