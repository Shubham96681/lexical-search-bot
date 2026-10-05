"""User-supplied documents stored beside the Ranger corpus."""

from __future__ import annotations

import json
import re
from pathlib import Path

from kb.corpus import ROOT, _policy_file_chunks, _prose_chunks, html_to_text

UPLOAD_DIR = ROOT / "data" / "uploads"
ALLOWED = {".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm", ".pdf", ".docx"}
MAX_BYTES = 10 * 1024 * 1024


def save_upload(filename: str, data: bytes) -> str:
    name = safe_name(filename)
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED:
        raise ValueError(f"{name} is not supported. Use text, Markdown, CSV, JSON, HTML, PDF, or Word.")
    if not data:
        raise ValueError(f"{name} is empty.")
    if len(data) > MAX_BYTES:
        raise ValueError(f"{name} is larger than 10 MB.")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / name
    path.write_bytes(data)
    try:
        chunks = chunks_for_file(path)
    except ValueError:
        path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise ValueError(f"Could not read {name}: {exc}") from exc
    if not chunks:
        path.unlink(missing_ok=True)
        raise ValueError(f"{name} did not contain enough readable text to index.")
    return name


def delete_upload(filename: str) -> None:
    path = _existing_upload(filename)
    path.unlink()


def load_upload_chunks() -> list[dict]:
    if not UPLOAD_DIR.exists():
        return []
    chunks: list[dict] = []
    for path in sorted(UPLOAD_DIR.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in ALLOWED:
            continue
        try:
            chunks.extend(chunks_for_file(path))
        except Exception:
            continue
    return chunks


def chunks_for_file(path: Path) -> list[dict]:
    title = path.stem.replace("_", " ").replace("-", " ")
    source = {
        "file": f"upload:{path.name}",
        "title": title,
        "url": "",
        "kind": "upload",
        "uploaded": True,
        "upload_name": path.name,
    }
    suffix = path.suffix.lower()
    if suffix == ".json" and _looks_like_policies(path):
        source["kind"] = "policy"
        return _policy_file_chunks(path, source)
    if suffix in {".html", ".htm"}:
        text = html_to_text(path.read_text(encoding="utf-8", errors="replace"))
    elif suffix == ".pdf":
        text = _pdf_text(path)
    elif suffix == ".docx":
        text = _docx_text(path)
    elif suffix == ".json":
        text = _json_text(path)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    return _prose_chunks(text, source)


def safe_name(filename: str) -> str:
    name = Path(filename or "").name.replace("\\", "_").replace("/", "_")
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
    if not name or name.startswith("."):
        raise ValueError("Choose a file with a normal name.")
    if Path(name).suffix.lower() not in ALLOWED:
        raise ValueError(f"{name} is not supported. Use text, Markdown, CSV, JSON, HTML, PDF, or Word.")
    return name


def _existing_upload(filename: str) -> Path:
    name = safe_name(filename)
    path = (UPLOAD_DIR / name).resolve()
    if path.parent != UPLOAD_DIR.resolve() or not path.is_file():
        raise FileNotFoundError(name)
    return path


def _looks_like_policies(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return _has_policies(data)


def _has_policies(node) -> bool:
    if isinstance(node, dict):
        policies = node.get("policies")
        if isinstance(policies, list) and any(
            isinstance(item, dict) and "name" in item and ("resources" in item or "policyItems" in item)
            for item in policies
        ):
            return True
        return any(_has_policies(value) for value in node.values() if isinstance(value, (dict, list)))
    if isinstance(node, list):
        return any(_has_policies(value) for value in node if isinstance(value, (dict, list)))
    return False


def _json_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        return json.dumps(json.loads(raw), indent=2, ensure_ascii=False)[:400_000]
    except json.JSONDecodeError:
        return raw[:400_000]


def _pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("PDF support is not installed.") from exc
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


def _docx_text(path: Path) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise ValueError("Word support is not installed.") from exc
    document = Document(str(path))
    parts = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    return "\n\n".join(parts)
