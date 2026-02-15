#!/usr/bin/env python3
"""Offline Anytype export -> Qdrant sync.

This ingests files exported from Anytype (Markdown/PDF/TXT) that you place on the server.
It does NOT require Anytype Local API to be running.

Design:
- Deterministic point IDs per (relpath, chunk_index) so updates overwrite.
- State file stores previous chunk_total; when chunk_total shrinks we delete extra old points.
"""

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import PurePosixPath
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Tuple

import requests

try:
    from pypdf import PdfReader  # type: ignore
except Exception:
    PdfReader = None


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _sha1_bytes(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def _sha1_text(t: str) -> str:
    return hashlib.sha1((t or "").encode("utf-8", errors="ignore")).hexdigest()


def _safe_relpath(path: str, base: str) -> str:
    p = os.path.abspath(path)
    b = os.path.abspath(base)
    if not (p == b or p.startswith(b + os.sep)):
        return os.path.basename(p)
    rel = os.path.relpath(p, b)
    rel = rel.replace("\\", "/")
    return rel


def _read_file_bytes(path: str, max_bytes: int) -> bytes:
    with open(path, "rb") as f:
        return f.read(max_bytes)


def _extract_text(path: str, ext: str, max_bytes: int = 2_000_000, max_chars: int = 200_000, max_pages: int = 30) -> str:
    e = (ext or "").lower().lstrip(".")
    try:
        if e in ("md", "txt"):
            raw = _read_file_bytes(path, max_bytes)
            try:
                text = raw.decode("utf-8", errors="ignore")
            except Exception:
                text = raw.decode("latin-1", errors="ignore")
            return (text or "")[:max_chars]
        if e == "pdf":
            if PdfReader is None:
                return ""
            pieces: List[str] = []
            total = 0
            reader = PdfReader(path)
            for i, page in enumerate(reader.pages):
                if i >= int(max_pages):
                    break
                try:
                    part = page.extract_text() or ""
                except Exception:
                    part = ""
                part = str(part or "")
                if not part.strip():
                    continue
                remain = int(max_chars) - total
                if remain <= 0:
                    break
                if len(part) > remain:
                    part = part[:remain]
                pieces.append(part)
                total += len(part)
                if total >= int(max_chars):
                    break
            return "\n".join(pieces).strip()
    except Exception:
        return ""
    return ""


def _split_text(text: str, chunk_size: int = 900, overlap: int = 120) -> List[str]:
    raw = str(text or "").strip()
    if not raw:
        return []

    # Simple paragraph-based packing; stable and language-agnostic.
    paras = [p.strip() for p in raw.replace("\r", "\n").split("\n") if str(p or "").strip()]
    chunks: List[str] = []
    cur = ""
    for p in paras:
        if not cur:
            cur = p
            continue
        if len(cur) + 1 + len(p) <= int(chunk_size):
            cur += "\n" + p
        else:
            chunks.append(cur)
            tail = cur[-int(overlap):] if int(overlap) > 0 else ""
            cur = (tail + "\n" + p).strip() if tail else p
    if cur:
        chunks.append(cur)

    out: List[str] = []
    for c in chunks:
        c = c.strip()
        if not c:
            continue
        if len(c) <= int(chunk_size):
            out.append(c)
            continue
        i = 0
        step = max(1, int(chunk_size) - int(overlap))
        while i < len(c):
            out.append(c[i : i + int(chunk_size)])
            i += step
    return out


def _ollama_embed(ollama_base: str, model: str, text: str, timeout_sec: float) -> List[float]:
    payload = {"model": model, "input": text}
    r = requests.post(ollama_base.rstrip("/") + "/api/embed", json=payload, timeout=timeout_sec)
    if int(getattr(r, "status_code", 0) or 0) >= 400:
        raise RuntimeError(f"embed_failed_http_{int(r.status_code)}")
    obj = r.json() if hasattr(r, "json") else {}
    embs = obj.get("embeddings") if isinstance(obj, dict) else []
    if not isinstance(embs, list) or len(embs) <= 0 or (not isinstance(embs[0], list)):
        raise RuntimeError("embed_invalid_response")
    return [float(x) for x in embs[0]]


def _qdrant_upsert(qdrant_url: str, collection: str, points: List[Dict[str, Any]], timeout_sec: float) -> None:
    url = qdrant_url.rstrip("/") + f"/collections/{collection}/points?wait=true"
    r = requests.put(url, json={"points": points}, timeout=timeout_sec)
    if int(getattr(r, "status_code", 0) or 0) >= 400:
        raise RuntimeError(f"qdrant_upsert_http_{int(r.status_code)}:{str(getattr(r, 'text', ''))[:200]}")


def _qdrant_delete_ids(qdrant_url: str, collection: str, ids: List[str], timeout_sec: float) -> None:
    if not ids:
        return
    url = qdrant_url.rstrip("/") + f"/collections/{collection}/points/delete?wait=true"
    r = requests.post(url, json={"points": ids}, timeout=timeout_sec)
    if int(getattr(r, "status_code", 0) or 0) >= 400:
        raise RuntimeError(f"qdrant_delete_http_{int(r.status_code)}:{str(getattr(r, 'text', ''))[:200]}")


def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, obj: Any) -> None:
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _iter_files(base_dir: str, exts: List[str]) -> List[str]:
    out: List[str] = []
    for root, _dirs, files in os.walk(base_dir):
        for fn in files:
            p = os.path.join(root, fn)
            e = os.path.splitext(fn)[1].lower().lstrip(".")
            if e and e in exts:
                out.append(p)
    out.sort()
    return out


def _point_id_for(relpath: str, chunk_index: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"anytype_export|{relpath}|{int(chunk_index)}"))


def _tags_for_export(export_dir: str, relpath: str, ext: str) -> List[str]:
    base = str(export_dir or "").replace("\\", "/").rstrip("/")
    rp = str(relpath or "").replace("\\", "/").lstrip("./")
    e = str(ext or "").lower().lstrip(".")
    tags = ["source:export", "connector:anytype_export"]
    if e:
        tags.append("ext:" + e)
    # Tag processed_md even when export_dir is already the processed_md root (relpath has no prefix).
    if base.lower().endswith("/processed_md") or base.lower().endswith("/processed-md"):
        tags.append("scope:processed_md")
    elif rp.startswith("processed_md/") or rp.startswith("processed-md/") or rp.startswith("processed/"):
        tags.append("scope:processed_md")
    # Add a few directory tags for scope filtering.
    parts = [p for p in PurePosixPath(rp).parts if p and p not in (".", "..")]
    for d in parts[:-1][:3]:
        tags.append("dir:" + str(d).lower())
    # Deduplicate while preserving order.
    out = []
    seen = set()
    for t in tags:
        tt = str(t or "").strip()
        if (not tt) or (tt in seen):
            continue
        seen.add(tt)
        out.append(tt)
    return out


def run(args) -> int:
    export_dir = _env("ANYTYPE_EXPORT_DIR", args.export_dir)
    export_dir = export_dir.strip()
    if not export_dir:
        print("ERROR: export dir is empty", file=sys.stderr)
        return 2
    if not os.path.isdir(export_dir):
        print(f"ERROR: export dir not found: {export_dir}", file=sys.stderr)
        return 2

    exts = [e.strip().lower().lstrip(".") for e in (args.exts or "md,txt,pdf").replace(";", ",").split(",") if e.strip()]
    if not exts:
        exts = ["md", "txt", "pdf"]

    ollama_base = _env("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    embed_model = _env("EMBED_MODEL", "qwen3-embedding:0.6b")
    qdrant_url = _env("QDRANT_URL", "http://127.0.0.1:6333")
    qdrant_collection = _env("QDRANT_COLLECTION", "ha_memory_qwen3")
    vector_size = int(_env("QDRANT_VECTOR_SIZE", "1024") or "1024")

    state = _load_json(args.state_file, {})
    files_state = state.get("files") if isinstance(state, dict) else None
    if not isinstance(files_state, dict):
        files_state = {}

    paths = _iter_files(export_dir, exts)

    scanned = 0
    changed = 0
    upserted = 0
    deleted = 0

    for p in paths:
        scanned += 1
        st = os.stat(p)
        mtime = float(getattr(st, "st_mtime", 0.0) or 0.0)
        size = int(getattr(st, "st_size", 0) or 0)
        rel = _safe_relpath(p, export_dir)

        prev = files_state.get(rel) if isinstance(files_state, dict) else None
        prev_mtime = float((prev or {}).get("mtime") or 0.0) if isinstance(prev, dict) else 0.0
        prev_size = int((prev or {}).get("size") or 0) if isinstance(prev, dict) else 0
        prev_chunks = int((prev or {}).get("chunk_total") or 0) if isinstance(prev, dict) else 0

        if (not args.full_reindex) and (abs(prev_mtime - mtime) < 0.000001) and (prev_size == size):
            continue

        ext = os.path.splitext(p)[1].lower().lstrip(".")
        text = _extract_text(p, ext)
        if not text.strip():
            files_state[rel] = {"mtime": mtime, "size": size, "chunk_total": 0, "sha1": ""}
            continue

        chunks = _split_text(text, chunk_size=args.chunk_size, overlap=args.chunk_overlap)
        chunks = [c for c in chunks if c.strip()]

        changed += 1

        # Delete old tail chunks if file shrank.
        if (not args.dry_run) and prev_chunks > len(chunks) and prev_chunks > 0:
            ids = [_point_id_for(rel, i) for i in range(len(chunks), prev_chunks)]
            _qdrant_delete_ids(qdrant_url, qdrant_collection, ids, timeout_sec=args.timeout_sec)
            deleted += len(ids)

        if not args.dry_run:
            points: List[Dict[str, Any]] = []
            for idx, chunk in enumerate(chunks):
                vec = _ollama_embed(ollama_base, embed_model, chunk, timeout_sec=args.timeout_sec)
                if len(vec) != vector_size:
                    raise RuntimeError(f"vector_size_mismatch got={len(vec)} expected={vector_size}")
                pid = _point_id_for(rel, idx)
                ext = os.path.splitext(rel)[1].lower().lstrip(".")
                payload = {
                    "source": "anytype_export",
                    "connector": "anytype_export",
                    "path": rel,
                    "relpath": rel,
                    "ext": ext,
                    "tags": _tags_for_export(export_dir, rel, ext),
                    "title": os.path.basename(rel),
                    "text": chunk,
                    "chunk_index": idx,
                    "chunk_total": len(chunks),
                    "updated_at": datetime.utcfromtimestamp(mtime).replace(microsecond=0).isoformat() + "Z",
                    "content_sha1": _sha1_text(chunk),
                    "file_sha1": _sha1_bytes(_read_file_bytes(p, 2_000_000)),
                    "sync_at": _now_iso(),
                }
                points.append({"id": pid, "vector": vec, "payload": payload})

                # Avoid huge request bodies.
                if len(points) >= 32:
                    _qdrant_upsert(qdrant_url, qdrant_collection, points, timeout_sec=args.timeout_sec)
                    upserted += len(points)
                    points = []

            if points:
                _qdrant_upsert(qdrant_url, qdrant_collection, points, timeout_sec=args.timeout_sec)
                upserted += len(points)

        files_state[rel] = {
            "mtime": mtime,
            "size": size,
            "chunk_total": len(chunks),
            "sha1": _sha1_bytes(_read_file_bytes(p, 2_000_000)),
            "updated_at": _now_iso(),
        }

    out_state = {
        "export_dir": export_dir,
        "last_run": _now_iso(),
        "stats": {
            "scanned": scanned,
            "changed": changed,
            "upserted": upserted,
            "deleted": deleted,
            "dry_run": bool(args.dry_run),
            "full_reindex": bool(args.full_reindex),
        },
        "files": files_state,
    }

    if not args.dry_run:
        _save_json(args.state_file, out_state)

    print(json.dumps(out_state.get("stats"), ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Offline Anytype export directory -> Qdrant sync")
    ap.add_argument("--export-dir", default="/mnt/nas/anytype_export")
    ap.add_argument("--state-file", default="/app/data/anytype_export_sync_state.json")
    ap.add_argument("--exts", default="md,txt,pdf")
    ap.add_argument("--chunk-size", type=int, default=900)
    ap.add_argument("--chunk-overlap", type=int, default=120)
    ap.add_argument("--timeout-sec", type=float, default=20.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--full-reindex", action="store_true")
    args = ap.parse_args()
    try:
        rc = run(args)
    except Exception as e:
        print("ERROR:", str(e), file=sys.stderr)
        rc = 1
    sys.exit(rc)


if __name__ == "__main__":
    main()
