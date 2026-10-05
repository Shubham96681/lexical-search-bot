"""Download Ranger documents and turn them into retrieval chunks."""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

from kb.sources import SOURCES

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"

POLICY_TYPES = {0: "access", 1: "data-mask", 2: "row-filter"}
CHUNK_CHARS = 1400

_USER_AGENT = "knowledge-base-chatbot/1.0 (local Ranger corpus)"


def download(force: bool = False) -> list[str]:
    """Fetch any corpus files that are not already on disk."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for source in SOURCES:
        path = RAW_DIR / source["file"]
        if path.exists() and not force:
            continue
        payload = _fetch(source["url"])
        if source["kind"] == "html":
            text = html_to_text(payload.decode("utf-8", errors="replace"))
            path.write_text(text, encoding="utf-8")
        else:
            path.write_bytes(payload)
        saved.append(source["file"])
    return saved


def load_chunks() -> list[dict]:
    download()
    chunks: list[dict] = []
    seen: set[str] = set()
    for source in SOURCES:
        path = RAW_DIR / source["file"]
        if not path.exists():
            continue
        if source["kind"] == "policy":
            produced = _policy_file_chunks(path, source)
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
            produced = _prose_chunks(text, source)
        for chunk in produced:
            _keep_chunk(chunk, chunks, seen)
    from kb.uploads import load_upload_chunks

    for chunk in load_upload_chunks():
        _keep_chunk(chunk, chunks, seen)
    for index, chunk in enumerate(chunks):
        chunk["id"] = f"c{index}"
    return chunks


def _keep_chunk(chunk: dict, chunks: list[dict], seen: set[str]) -> None:
    key = chunk["text"].strip()
    if len(key) < 40 or key in seen:
        return
    seen.add(key)
    chunks.append(chunk)


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script, style, noscript, svg, .navbar, footer, .subfooter, #banner"):
        tag.decompose()
    main = soup.select_one("div.container") or soup.body or soup
    text = main.get_text("\n", strip=True).replace("\ufffd", "-")
    lines = []
    previous = None
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or line == previous:
            continue
        if line in {"Get Started", "[top]"} or line.startswith("←"):
            continue
        if len(line) < 2:
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines)


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _policy_file_chunks(path: Path, source: dict) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    groups: list[tuple[str, list]] = []
    definitions: list[tuple[str, dict]] = []
    _collect(data, groups, definitions)

    chunks: list[dict] = []
    for service_name, service_def in definitions:
        rendered = _render_service_def(service_name, service_def)
        if rendered:
            chunks.append(
                _make_chunk(
                    source,
                    f"{service_name} service definition",
                    rendered,
                    _service_summary(service_name, service_def),
                )
            )

    for service_name, policies in groups:
        for policy in policies:
            title = str(policy.get("name") or "unnamed policy")
            chunks.append(
                _make_chunk(
                    source,
                    f"{service_name}: {title}",
                    _render_policy(service_name, policy, source["title"]),
                    _policy_summary(service_name, policy),
                )
            )
    return chunks


def _collect(node, groups: list, definitions: list) -> None:
    if isinstance(node, dict):
        policies = node.get("policies")
        if isinstance(policies, list):
            real = [
                item
                for item in policies
                if isinstance(item, dict)
                and "name" in item
                and any(key in item for key in ("resources", "policyItems", "denyPolicyItems", "dataMaskPolicyItems", "rowFilterPolicyItems"))
            ]
            if real:
                service = str(node.get("serviceName") or real[0].get("service") or "unknown")
                groups.append((service, real))
        service_def = node.get("serviceDef")
        if isinstance(service_def, dict) and (service_def.get("resources") or service_def.get("accessTypes")):
            service_name = str(node.get("serviceName") or service_def.get("name") or "unknown")
            definitions.append((service_name, service_def))
        for value in node.values():
            if isinstance(value, (dict, list)):
                _collect(value, groups, definitions)
    elif isinstance(node, list):
        for value in node:
            if isinstance(value, (dict, list)):
                _collect(value, groups, definitions)


def _render_service_def(service_name: str, service_def: dict) -> str:
    lines = [
        f"Service definition for {service_def.get('name') or service_name}.",
        f"Service: {service_name}.",
        "This describes the resource hierarchy and permissions Ranger can authorize.",
    ]
    resources = service_def.get("resources") or []
    if resources:
        lines.append("Resources:")
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            parent = resource.get("parent")
            parent_text = f", parent {parent}" if parent else ""
            level = resource.get("level")
            level_text = f", level {level}" if level is not None else ""
            label = resource.get("description") or resource.get("label") or ""
            lines.append(f"- {resource.get('name')}{level_text}{parent_text}. {label}".rstrip())
    accesses = service_def.get("accessTypes") or []
    if accesses:
        lines.append("Access types:")
        for access in accesses:
            if not isinstance(access, dict):
                continue
            implied = access.get("impliedGrants") or []
            extra = f" (implies {', '.join(implied)})" if implied else ""
            lines.append(f"- {access.get('name')}{extra}")
    return "\n".join(lines)


def _policy_summary(service_name: str, policy: dict) -> str:
    name = str(policy.get("name") or "unnamed policy")
    service = str(policy.get("service") or service_name)
    resources = _resource_phrase(policy.get("resources") or {})
    sentence = f'Policy "{name}" on {service}'
    if resources:
        sentence += f" covers {resources}"
    if policy.get("isEnabled") is False:
        sentence += ", and it is turned off"
    clauses = []
    for verb, items in (
        ("allows", policy.get("policyItems")),
        ("denies", policy.get("denyPolicyItems")),
        ("allows, as an exception,", policy.get("allowExceptions")),
        ("denies, as an exception,", policy.get("denyExceptions")),
        ("masks data for", policy.get("dataMaskPolicyItems")),
        ("limits rows for", policy.get("rowFilterPolicyItems")),
    ):
        for item in items or []:
            if isinstance(item, dict):
                clause = _item_clause(verb, item)
                if clause:
                    clauses.append(clause)
    if clauses:
        return sentence + ". " + " ".join(clauses)
    return sentence + "."


def _service_summary(service_name: str, service_def: dict) -> str:
    name = service_def.get("name") or service_name
    resources = [
        resource.get("name")
        for resource in service_def.get("resources") or []
        if isinstance(resource, dict) and resource.get("name")
    ]
    accesses = [
        access.get("name")
        for access in service_def.get("accessTypes") or []
        if isinstance(access, dict) and access.get("name") and access.get("name") != "all"
    ]
    resource_text = _phrase(resources) if resources else "its resources"
    access_text = _phrase(accesses[:8]) if accesses else "the permissions defined for that service"
    return f"The {name} service can protect {resource_text}. People can be granted {access_text}."


def _resource_phrase(resources: dict) -> str:
    parts = []
    for name, spec in resources.items():
        if not isinstance(spec, dict):
            continue
        values = [str(value) for value in (spec.get("values") or [])]
        if not values:
            continue
        notes = []
        if spec.get("isRecursive"):
            notes.append("including everything under it" if name == "path" else "including child resources")
        if spec.get("isExcludes"):
            notes.append("these values are excluded")
        note = f" ({'; '.join(notes)})" if notes else ""
        parts.append(f"{name} {_phrase(values)}{note}")
    return ", ".join(parts)


def _item_clause(verb: str, item: dict) -> str:
    who = []
    users = [str(value) for value in (item.get("users") or [])]
    groups = [str(value) for value in (item.get("groups") or [])]
    roles = [str(value) for value in (item.get("roles") or [])]
    if users:
        who.append(f"{'user' if len(users) == 1 else 'users'} {_phrase(users)}")
    if groups:
        who.append(f"{'group' if len(groups) == 1 else 'groups'} {_phrase(groups)}")
    if roles:
        who.append(f"{'role' if len(roles) == 1 else 'roles'} {_phrase(roles)}")
    audience = " and ".join(who) if who else "the listed principals"
    accesses = []
    for access in item.get("accesses") or []:
        if isinstance(access, dict) and access.get("type"):
            accesses.append(str(access["type"]))
        elif isinstance(access, str):
            accesses.append(access)
    if verb == "masks data for":
        mask = item.get("dataMaskInfo") or {}
        kind = mask.get("dataMaskType") or "a masking rule"
        return f"It masks data for {audience} with {kind}."
    if verb == "limits rows for":
        expression = (item.get("rowFilterInfo") or {}).get("filterExpr") or "a row filter"
        return f"It limits {audience} to rows matching {expression}."
    if accesses:
        return f"It {verb} {audience} to {_phrase(accesses)}."
    if item.get("delegateAdmin"):
        return f"It lets {audience} administer this policy."
    return ""


def _phrase(values: list[str]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return ", ".join(values[:-1]) + f", and {values[-1]}"


def _render_policy(service_name: str, policy: dict, document_title: str) -> str:
    policy_type = policy.get("policyType", 0)
    type_name = POLICY_TYPES.get(policy_type, str(policy_type))
    lines = [
        f"Document: {document_title}.",
        f"Service: {policy.get('service') or service_name}.",
        f"Policy name: {policy.get('name')}.",
        f"Policy id: {policy.get('id', 'n/a')}.",
        f"Policy type: {type_name}.",
        f"Enabled: {policy.get('isEnabled', True)}.",
        f"Audit enabled: {policy.get('isAuditEnabled', True)}.",
    ]
    if policy.get("description"):
        lines.append(f"Description: {policy['description']}.")
    if policy.get("policyPriority") is not None:
        lines.append(f"Priority: {policy['policyPriority']}.")
    if policy.get("zoneName"):
        lines.append(f"Security zone: {policy['zoneName']}.")

    resources = policy.get("resources") or {}
    if resources:
        lines.append("Resources:")
        lines.extend(_render_resources(resources))

    _append_items(lines, "Allow", policy.get("policyItems"))
    _append_items(lines, "Deny", policy.get("denyPolicyItems"))
    _append_items(lines, "Allow exceptions", policy.get("allowExceptions"))
    _append_items(lines, "Deny exceptions", policy.get("denyExceptions"))
    _append_items(lines, "Data masking", policy.get("dataMaskPolicyItems"))
    _append_items(lines, "Row filters", policy.get("rowFilterPolicyItems"))
    return "\n".join(lines)


def _render_resources(resources: dict) -> list[str]:
    lines = []
    for name, spec in resources.items():
        if not isinstance(spec, dict):
            lines.append(f"- {name}: {spec}")
            continue
        values = ", ".join(str(value) for value in (spec.get("values") or []))
        flags = []
        if spec.get("isRecursive"):
            flags.append("recursive")
        if spec.get("isExcludes"):
            flags.append("excludes these values")
        flag_text = f" ({', '.join(flags)})" if flags else ""
        lines.append(f"- {name}: {values}{flag_text}")
    return lines


def _append_items(lines: list[str], label: str, items) -> None:
    if not items:
        return
    lines.append(f"{label}:")
    for item in items:
        if isinstance(item, dict):
            lines.append(f"- {_render_item(item)}")


def _render_item(item: dict) -> str:
    parts: list[str] = []
    for key, label in (("users", "users"), ("groups", "groups"), ("roles", "roles")):
        values = item.get(key) or []
        if values:
            parts.append(f"{label}: {', '.join(str(value) for value in values)}")
    accesses = []
    for access in item.get("accesses") or []:
        if isinstance(access, dict) and access.get("type"):
            allowed = access.get("isAllowed", True)
            accesses.append(access["type"] if allowed else f"{access['type']} (not allowed)")
        elif isinstance(access, str):
            accesses.append(access)
    if accesses:
        parts.append(f"access: {', '.join(accesses)}")
    if item.get("delegateAdmin"):
        parts.append("delegate admin")
    conditions = item.get("conditions") or []
    if conditions:
        parts.append("conditions: " + _compact(conditions))
    if item.get("dataMaskInfo"):
        parts.append("mask: " + _compact(item["dataMaskInfo"]))
    if item.get("rowFilterInfo"):
        parts.append("row filter: " + _compact(item["rowFilterInfo"]))
    return "; ".join(parts) if parts else "empty policy item"


def _compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def _prose_chunks(text: str, source: dict) -> list[dict]:
    cleaned = re.sub(r"(?s)<!--.*?-->", " ", text)
    cleaned = cleaned.replace("\r\n", "\n")
    blocks = _split_prose(_reflow(cleaned))
    chunks = []
    for block in blocks:
        body = block.strip()
        chunks.append(_make_chunk(source, source["title"], body, _prose_summary(body)))
    return chunks


def _reflow(text: str) -> str:
    """Join broken HTML lines into paragraphs, keeping real headings separate."""
    text = (
        text.replace("-€“", " — ")
        .replace("-€™", "'")
        .replace("-€-", '"')
        .replace("â€™", "'")
        .replace("â€“", "—")
        .replace("â€œ", '"')
    )
    paragraphs: list[str] = []
    bucket: list[str] = []

    def flush() -> None:
        if bucket:
            paragraphs.append(" ".join(bucket))
            bucket.clear()

    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or line in {"Get Started", "[top]"} or line.startswith("←"):
            flush()
            continue
        if _looks_like_heading(line):
            flush()
            paragraphs.append(line)
            continue
        bucket.append(line)
        if line.endswith((".", "?", "!")) and len(" ".join(bucket)) > 80:
            flush()
    flush()
    return "\n\n".join(paragraphs)


def _looks_like_heading(line: str) -> bool:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9,;&/\- ]{2,68}", line):
        return False
    words = line.split()
    if not 1 <= len(words) <= 8:
        return False
    if len(words) == 1:
        return bool(re.fullmatch(r"[A-Z][a-z]{3,}", line))
    titled = sum(1 for word in words if word[:1].isupper())
    return titled >= max(1, len(words) // 2)


def _split_prose(text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    packed: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > CHUNK_CHARS:
            packed.append(current.strip())
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current.strip():
        packed.append(current.strip())
    return packed or [text.strip()]


def _prose_summary(text: str) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", flat)
    kept: list[str] = []
    for sentence in sentences:
        if len(sentence) < 40:
            continue
        kept.append(sentence)
        if len(kept) == 2:
            break
    summary = " ".join(kept) if kept else flat
    return _clip(summary, 320)


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return f"{cut}…"


def _make_chunk(source: dict, title: str, text: str, summary: str) -> dict:
    return {
        "title": title,
        "text": text.strip(),
        "summary": summary.strip(),
        "source": source["file"],
        "document": source["title"],
        "url": source.get("url") or "",
        "kind": source["kind"],
        "uploaded": bool(source.get("uploaded")),
        "upload_name": source.get("upload_name") or "",
    }
