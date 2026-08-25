"""Fetch a source and reduce it to plain body text. Side effects live here."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

from .models import Document, Source, SourceKind

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 milisten/0.1"
MIN_BODY = 400


class ExtractionError(RuntimeError):
    pass


def detect_kind(ref: str) -> SourceKind:
    """Extensions are a hint, not an answer — arXiv serves PDFs from extensionless URLs."""
    stem = ref.lower().split("?")[0].split("#")[0]
    if stem.endswith(".pdf"):
        return SourceKind.PDF
    if stem.endswith((".txt", ".md")):
        return SourceKind.TEXT
    if stem.endswith((".html", ".htm")):
        return SourceKind.HTML
    return SourceKind.AUTO


def sniff(data: bytes, content_type: str = "") -> SourceKind:
    head = data[:4096]
    if head.startswith(b"%PDF-") or "application/pdf" in content_type:
        return SourceKind.PDF
    if "text/html" in content_type or b"<html" in head.lower() or b"<!doctype" in head.lower():
        return SourceKind.HTML
    return SourceKind.TEXT


def resolve(kind: SourceKind, data: bytes, content_type: str = "") -> SourceKind:
    return sniff(data, content_type) if kind is SourceKind.AUTO else kind


def fetch(url: str) -> tuple[bytes, str]:
    with httpx.Client(follow_redirects=True, timeout=90.0, headers={"User-Agent": UA}) as client:
        response = client.get(url)
        response.raise_for_status()
    return response.content, response.headers.get("content-type", "")


def html_to_text(markup: str, origin: str) -> str:
    import trafilatura

    body = trafilatura.extract(
        markup, include_comments=False, include_tables=True, favor_recall=True
    )
    if not body or len(body) < MIN_BODY:
        raise ExtractionError(
            f"only {len(body or '')} chars recovered from {origin} — likely paywalled or "
            "script-rendered; save the page or PDF locally and add the file instead"
        )
    return body


def pdf_to_text(path: Path, layout: bool = False) -> str:
    if not shutil.which("pdftotext"):
        raise ExtractionError("pdftotext not found — install poppler (brew install poppler)")
    cmd = ["pdftotext", "-enc", "UTF-8", *(["-layout"] if layout else [])]
    result = subprocess.run(
        [*cmd, str(path), "-"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise ExtractionError(f"pdftotext failed on {path}: {result.stderr.strip()}")
    if len(result.stdout.strip()) < MIN_BODY:
        raise ExtractionError(f"{path} yielded no extractable text — it may be a scan needing OCR")
    return result.stdout


def _from_bytes(raw: bytes, kind: SourceKind, origin: str, layout: bool) -> str:
    if kind is SourceKind.PDF:
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "in.pdf"
            local.write_bytes(raw)
            return pdf_to_text(local, layout)
    text = raw.decode("utf-8", errors="replace")
    return html_to_text(text, origin) if kind is SourceKind.HTML else text


def extract(source: Source, layout: bool = False) -> Document:
    if source.is_local:
        path = Path(source.ref).expanduser()
        if not path.exists():
            raise ExtractionError(f"{path} not found")
        kind = resolve(source.kind, path.read_bytes()[:4096])
        if kind is SourceKind.PDF:
            return Document(source, pdf_to_text(path, layout))
        return Document(source, _from_bytes(path.read_bytes(), kind, str(path), layout))

    raw, content_type = fetch(source.ref)
    kind = resolve(source.kind, raw, content_type)
    return Document(source, _from_bytes(raw, kind, source.ref, layout))
