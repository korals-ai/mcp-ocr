# Workspace-tool sidecar (ocr): a per-chat co-located helper that OCRs scanned
# PDFs (image-only → searchable) and exposes it as an MCP tool over Streamable
# HTTP. The workspace agent calls it as mcp__workspace-tool-ocr__ocr instead of
# carrying OCRmyPDF + Tesseract + Ghostscript in the per-chat workspace image.
#
# Design + rationale: docs/plan/20260619-200506-toolspace-sidecar.md (the
# workspace-tools sidecar substrate). One per tool family.

FROM python:3.12-slim AS py-builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc musl-dev \
  && rm -rf /var/lib/apt/lists/*

COPY workspace-tools/ocr/requirements.txt .

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim

# OCR toolchain:
#   * tesseract-ocr + tesseract-ocr-eng — the OCR engine + English language
#     data. Add tesseract-ocr-<lang> packages (and SUPPORTED_LANGUAGES in
#     ocr_convert.py) together when a tender corpus needs another language.
#   * ghostscript — OCRmyPDF rasterizes/repacks PDFs through gs.
#   * unpaper / pngquant — optional OCRmyPDF preprocessing/optimization helpers
#     it shells out to when present (clean-up + smaller output).
#   * ca-certificates — TLS baseline.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      tesseract-ocr \
      tesseract-ocr-eng \
      ghostscript \
      unpaper \
      pngquant \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=py-builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=py-builder /usr/local/bin /usr/local/bin

COPY workspace-tools/ocr/src ./src
# The one log format every tool image installs (apps/workspace-tools/toollog).
# COPY'd next to src, imported as `toollog` under `python -m` from /app — the
# same shape connector_base uses. Stdlib-only, so it adds no requirements.
COPY workspace-tools/toollog ./toollog

# The shared stalled-loop watchdog (apps/workspace-tools/loopwatch). Same
# placement and import rules as toollog above: COPY'd next to src, imported
# as `loopwatch` under `python -m` from /app.
COPY workspace-tools/loopwatch ./loopwatch


ENV PYTHONPATH=/app

# Mirror the workspace pod's unprivileged identity (uid/gid 65532) so files
# this sidecar writes onto the shared tenant PVC carry the ownership the main
# container expects (fsGroup 65532).
RUN groupadd --system --gid 65532 tool \
 && useradd --system --uid 65532 --gid 65532 --home-dir /home/tool --shell /bin/bash tool \
 && mkdir -p /home/tool \
 && chown -R tool:tool /home/tool
ENV HOME=/home/tool

EXPOSE 8091

USER tool

ENTRYPOINT ["python", "-m", "src.server"]
