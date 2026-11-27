# syntax=docker/dockerfile:1.7
#
# One image for every backend role: api, worker, beat, migrate, seed.
# The role is chosen by the command (see docker-compose.yml / k8s manifests).
#
#   builder  installs pinned deps into a venv, CPU-only torch
#   models   downloads the ML models once, at build time (no network at runtime)
#   runtime  slim, non-root, read-only-friendly
#
# Multi-arch: the same Dockerfile builds linux/amd64 and linux/arm64 (the free
# Oracle VM is ARM). The PyTorch CPU index serves wheels for both.

ARG PYTHON_VERSION=3.12
ARG TORCH_VERSION=2.15.0

FROM python:${PYTHON_VERSION}-slim AS builder
ARG TORCH_VERSION
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /src
RUN pip install "torch==${TORCH_VERSION}" --index-url https://download.pytorch.org/whl/cpu
COPY requirements.lock .
RUN pip install -r requirements.lock
COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN pip install --no-deps .

FROM builder AS models
# Bake both models into the image so pods never download at start-up.
ENV HF_HOME=/opt/hf
RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', device='cpu'); \
CrossEncoder('cross-encoder/nli-deberta-v3-xsmall', device='cpu')" \
 && python -c "import spacy; spacy.load('en_core_web_sm')"

FROM python:${PYTHON_VERSION}-slim AS runtime
LABEL org.opencontainers.image.source="https://github.com/sohumcs/specforge" \
      org.opencontainers.image.description="SPECForge backend: FastAPI API, Celery worker/beat, migrations" \
      org.opencontainers.image.licenses="MIT"
ARG GIT_SHA=dev
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false \
    GIT_SHA=${GIT_SHA}
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home /app app \
 && apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*
# ^ apt-get upgrade applies Debian security fixes published after the base image
#   was built (CI's Trivy gate fails on fixable HIGH/CRITICAL).
COPY --from=builder /opt/venv /opt/venv
COPY --from=models /opt/hf /opt/hf
WORKDIR /app
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app
USER 10001:10001
EXPOSE 8000 9100
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"
# Default role: API. --proxy-headers so client IPs (rate limits) come from the proxy.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
