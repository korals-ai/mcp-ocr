"""Toolspace sidecar (ocr) — MCP server over Streamable HTTP.

Exposes OCR (scanned-PDF → searchable-PDF) as an MCP tool the workspace agent
calls over ``http://localhost:<WORKSPACE_TOOL_PORT>/mcp``. Same substrate as
workspace-tool-office: co-located in the workspace pod, shares the tenant PVC, so
the file stays on the shared mount and the RPC carries only the path + verdict.

The bind port is REQUIRED via WORKSPACE_TOOL_PORT (the operator injects it,
distinct per co-located sidecar — one pod, one port space; ocr is 8091 in the
roster). Unset ⇒ the process exits at import rather than binding a guessed port.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from src.ocr_convert import (
    SUPPORTED_LANGUAGES,
    OcrError,
)
from src.ocr_convert import (
    ocr as _ocr,
)

log = logging.getLogger("workspace-tool-ocr")

HOST = "0.0.0.0"  # noqa: S104 - pod-local bind; nothing injects a host, the pod netns is the fence
PORT = int(os.environ["WORKSPACE_TOOL_PORT"])

mcp = FastMCP("ocr", host=HOST, port=PORT)


@mcp.tool()
def ocr(src: str, language: str = "eng") -> str:
    """Add a searchable text layer to a scanned PDF (OCR).

    Use this when a PDF is image-only (a scan) and text extraction returns
    nothing — common for scanned tender documents. Pages that already contain
    text are passed through untouched; only image pages are OCR'd.

    Args:
        src: Absolute path to the source PDF on the shared workspace volume
            (e.g. ``/home/agent/scan.pdf``). Read in place.
        language: Tesseract language code; defaults to ``eng``.

    Returns:
        The absolute path of the searchable PDF (``<stem>.ocr.pdf`` next to the
        source), as a string.

    Raises:
        OCR failures (missing/encrypted/non-PDF source, unsupported language,
        ocrmypdf error or timeout) surface as an MCP tool error.
    """
    source = Path(src)
    started = time.monotonic()
    try:
        out = _ocr(source, language=language)
    except OcrError as exc:
        # One structured line per call (keys match the office sidecar) so
        # Loki can chart error rate without per-pod scraping.
        log.warning(
            "tool=ocr op=ocr outcome=error dur_ms=%d lang=%s src=%s err=%s",
            int((time.monotonic() - started) * 1000),
            language,
            source.name,
            exc,
        )
        detail = f": {exc.stderr.strip()}" if exc.stderr else ""
        raise OcrError(f"{exc}{detail}") from exc
    log.info(
        "tool=ocr op=ocr outcome=ok dur_ms=%d lang=%s src=%s",
        int((time.monotonic() - started) * 1000),
        language,
        source.name,
    )
    return str(out)


def main() -> None:
    """Run the MCP server forever over Streamable HTTP. Blocks; entrypoint."""
    logging.basicConfig(level=logging.INFO)
    log.info(
        "workspace-tool-ocr MCP server on %s:%d (/mcp) — languages: %s",
        HOST,
        PORT,
        ", ".join(SUPPORTED_LANGUAGES),
    )
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
