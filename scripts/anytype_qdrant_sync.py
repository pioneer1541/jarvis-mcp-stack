#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Tuple

import requests


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _parse_iso(ts: str):
    t = str(ts or "").strip()
    if not t:
        return None
    t = t.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(t)
    except Exception:
        return None


def _iso_ge(a: str, b: str) -> bool:
    da = _parse_iso(a)
    db = _parse_iso(b)
    if da is not None and db is not None:
        return da >= db
    return str(a or "") >= str(b or "")


def _sha1(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8", errors="ignore")).hexdigest()


def _tags_for_anytype(space_id: str, object_id: str, title: str = "") -> List[str]:
    sid = str(space_id or "").strip()
    oid = str(object_id or "").strip()
    tags = ["source:anytype", "connector:anytype"]
    if sid:
        tags.append("space:" + sid)
    if oid:
        tags.append("object:" + oid)
    # Coarse title tag (safe, low-cardinality).
    t = str(title or "").strip().lower()
    if t:
        t = re.sub(r"[^a-z0-9\\-\\s]", " ", t)
        t = re.sub(r"\\s+", " ", t).strip()
        if t:
            tags.append("title:" + t[:24].strip())
    out = []
    seen = set()
    for x in tags:
        xx = str(x or "").strip()
        if (not xx) or (xx in seen):
            continue
        seen.add(xx)
        out.append(xx)
    return out


def _split_text(text: str, chunk_size: int = 900, overlap: int = 120) -> List[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    paras = [p.strip() for p in raw.replace("\r", "\n").split("\n") if str(p or "").strip()]
    chunks = []
    cur = ""
    for p in paras:
        if not cur:
            cur = p
            continue
        if len(cur) + 1 + len(p) <= chunk_size:
            cur += "\n" + p
        else:
            chunks.append(cur)
            tail = cur[-overlap:] if overlap > 0 else ""
            cur = (tail + "\n" + p).strip() if tail else p
    if cur:
        chunks.append(cur)
    out = []
    for c in chunks:
        c = c.strip()
        if not c:
            continue
        if len(c) <= chunk_size:
            out.append(c)
            continue
        i = 0
        step = max(1, chunk_size - overlap)
        while i < len(c):
            out.append(c[i : i + chunk_size])
            i += step
    return out


def _flatten_text(obj: Any) -> str:
    lines: List[str] = []

    def walk(v: Any):
        if v is None:
            return
        if isinstance(v, str):
            s = v.strip()
            if s:
                lines.append(s)
            return
        if isinstance(v, (int, float, bool)):
            lines.append(str(v))
            return
        if isinstance(v, list):
            for x in v:
                walk(x)
            return
        if isinstance(v, dict):
            # Unwrap common Anytype API response envelopes.
            for k in ("object", "data", "result"):
                if k in v:
                    walk(v.get(k))
            for k in (
                "title",
                "name",
                "text",
                "description",
                "content",
                "markdown",
                "snippet",
                "value",
            ):
                if k in v:
                    walk(v.get(k))
            for k in ("blocks", "details", "properties", "fields", "children"):
                if k in v:
                    walk(v.get(k))
            return

    walk(obj)
    dedup = []
    seen = set()
    for s in lines:
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        dedup.append(s)
    text = "\n".join(dedup).strip()
    if len(text) > 120000:
        text = text[:120000]
    return text


class AnytypeClient:
    def __init__(self, base_url: str, api_key: str, space_id: str = "", timeout_sec: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.space_id = str(space_id or "").strip()
        self.timeout_sec = float(timeout_sec)
        self.s = requests.Session()
        self.s.headers.update({"Content-Type": "application/json"})
        if api_key:
            self.s.headers.update({"Authorization": "Bearer " + api_key})
        ver = _env("ANYTYPE_VERSION", "")
        if ver:
            self.s.headers.update({"Anytype-Version": ver})

    def _url(self, path: str) -> str:
        p = "/" + str(path or "").lstrip("/")
        return self.base_url + p

    def _post_first_ok(self, paths: List[str], body: Dict[str, Any]) -> Dict[str, Any]:
        last = {}
        for p in paths:
            try:
                r = self.s.post(self._url(p), json=body, timeout=self.timeout_sec)
                if int(r.status_code) < 400:
                    return r.json() if hasattr(r, "json") else {}
                last = {"path": p, "status": int(r.status_code), "body": str(getattr(r, "text", ""))[:300]}
            except Exception as e:
                last = {"path": p, "error": str(e)}
        return {"error": "all_search_paths_failed", "last": last}

    def _get_first_ok(self, paths: List[str]) -> Dict[str, Any]:
        last = {}
        for p in paths:
            try:
                r = self.s.get(self._url(p), timeout=self.timeout_sec)
                if int(r.status_code) < 400:
                    return r.json() if hasattr(r, "json") else {}
                last = {"path": p, "status": int(r.status_code), "body": str(getattr(r, "text", ""))[:300]}
            except Exception as e:
                last = {"path": p, "error": str(e)}
        return {"error": "all_get_paths_failed", "last": last}

    def search_objects(self, offset: int, limit: int, since_iso: str = "") -> Dict[str, Any]:
        paths = []
        if self.space_id:
            paths.append(f"/v1/spaces/{self.space_id}/search")
        paths.extend(["/v1/search", "/search"])

        base_body = {
            "query": "",
            "offset": int(offset),
            "limit": int(limit),
        }
        bodies = []

        # Newer schema: sort as object
        b1 = dict(base_body)
        b1["sort"] = {"field": "last_modified_date", "direction": "asc"}
        if since_iso:
            b1["filter"] = {"last_modified_date": {"gte": since_iso}}
        bodies.append(b1)

        # Fallback: sort as object with order key
        b2 = dict(base_body)
        b2["sort"] = {"field": "last_modified_date", "order": "asc"}
        if since_iso:
            b2["filter"] = {"last_modified_date": {"gte": since_iso}}
        bodies.append(b2)

        # Fallback: no sort/filter (maximize compatibility)
        b3 = dict(base_body)
        bodies.append(b3)

        last = {}
        for body in bodies:
            resp = self._post_first_ok(paths, body)
            if isinstance(resp, dict) and not resp.get("error"):
                return resp
            last = resp if isinstance(resp, dict) else {"error": "invalid_response"}
        return {"error": "all_search_attempts_failed", "last": last}

    def get_object(self, object_id: str) -> Dict[str, Any]:
        oid = str(object_id or "").strip()
        if not oid:
            return {}
        paths = []
        if self.space_id:
            paths.append(f"/v1/spaces/{self.space_id}/objects/{oid}")
        paths.extend([f"/v1/objects/{oid}", f"/objects/{oid}"])
        return self._get_first_ok(paths)


def _extract_records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    for key in ("records", "objects", "items", "results", "list", "data"):
        v = payload.get(key)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
        if isinstance(v, dict):
            for k2 in ("records", "objects", "items", "results", "list"):
                v2 = v.get(k2)
                if isinstance(v2, list):
                    return [x for x in v2 if isinstance(x, dict)]
    return []


def _record_id(rec: Dict[str, Any]) -> str:
    for k in ("id", "object_id", "objectId", "record_id", "recordId"):
        v = rec.get(k)
        if v:
            return str(v)
    return ""


def _record_updated_at(rec: Dict[str, Any]) -> str:
    for k in (
        "last_modified_date",
        "lastModifiedDate",
        "updated_at",
        "updatedAt",
        "modified_at",
        "modifiedAt",
        "created_at",
        "createdAt",
    ):
        v = rec.get(k)
        if v:
            return str(v)
    return ""


def _record_title(rec: Dict[str, Any]) -> str:
    for k in ("title", "name"):
        v = rec.get(k)
        if v:
            return str(v)
    details = rec.get("details")
    if isinstance(details, dict):
        for k in ("title", "name"):
            v = details.get(k)
            if v:
                return str(v)
    return ""


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
    body = {"points": points}
    r = requests.put(url, json=body, timeout=timeout_sec)
    if int(getattr(r, "status_code", 0) or 0) >= 400:
        raise RuntimeError(f"qdrant_upsert_http_{int(r.status_code)}:{str(getattr(r, 'text', ''))[:200]}")


def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, obj: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def run(args) -> int:
    anytype_base = _env("ANYTYPE_API_BASE", "http://127.0.0.1:31009")
    anytype_key = _env("ANYTYPE_API_KEY", "")
    anytype_space = _env("ANYTYPE_SPACE_ID", "")
    ollama_base = _env("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    embed_model = _env("EMBED_MODEL", "qwen3-embedding:0.6b")
    qdrant_url = _env("QDRANT_URL", "http://127.0.0.1:6333")
    qdrant_collection = _env("QDRANT_COLLECTION", "ha_memory_qwen3")
    vector_size = int(_env("QDRANT_VECTOR_SIZE", "1024") or "1024")

    if not anytype_key:
        print("ERROR: ANYTYPE_API_KEY is empty", file=sys.stderr)
        return 2

    os.makedirs(os.path.dirname(args.state_file), exist_ok=True)
    state = _load_json(args.state_file, {})
    cursor = "" if args.full_reindex else str(state.get("cursor") or "")

    client = AnytypeClient(anytype_base, anytype_key, anytype_space, timeout_sec=args.timeout_sec)

    offset = 0
    max_updated = cursor
    scanned = 0
    changed = 0
    upserted = 0
    pages = 0

    while pages < args.max_pages:
        page = client.search_objects(offset=offset, limit=args.page_size, since_iso=("" if args.full_reindex else cursor))
        if isinstance(page, dict) and page.get("error"):
            print("ERROR: search failed", json.dumps(page, ensure_ascii=False), file=sys.stderr)
            return 3
        rows = _extract_records(page)
        if not rows:
            break

        pages += 1
        scanned += len(rows)

        for rec in rows:
            oid = _record_id(rec)
            if not oid:
                continue
            updated = _record_updated_at(rec)
            if (not args.full_reindex) and cursor and updated and (not _iso_ge(updated, cursor)):
                continue

            detail = client.get_object(oid)
            if isinstance(detail, dict) and detail.get("error"):
                detail = rec

            title = _record_title(detail) or _record_title(rec)
            obj_text = _flatten_text(detail if isinstance(detail, dict) else rec)
            if not obj_text:
                continue

            chunks = _split_text(obj_text, chunk_size=args.chunk_size, overlap=args.chunk_overlap)
            if not chunks:
                continue

            changed += 1
            points = []
            for idx, chunk in enumerate(chunks):
                if len(chunk.strip()) < 4:
                    continue
                if args.dry_run:
                    continue
                vec = _ollama_embed(ollama_base, embed_model, chunk, timeout_sec=args.timeout_sec)
                if len(vec) != vector_size:
                    raise RuntimeError(f"vector_size_mismatch got={len(vec)} expected={vector_size}")
                pid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"anytype|{oid}|{idx}"))
                payload = {
                    "source": "anytype",
                    "connector": "anytype",
                    "space_id": anytype_space,
                    "object_id": oid,
                    "tags": _tags_for_anytype(anytype_space, oid, title),
                    "title": title,
                    "text": chunk,
                    "chunk_index": idx,
                    "chunk_total": len(chunks),
                    "updated_at": updated,
                    "content_sha1": _sha1(chunk),
                    "sync_at": _now_iso(),
                }
                points.append({"id": pid, "vector": vec, "payload": payload})

            if (not args.dry_run) and points:
                _qdrant_upsert(qdrant_url, qdrant_collection, points, timeout_sec=args.timeout_sec)
                upserted += len(points)

            if updated and ((not max_updated) or _iso_ge(updated, max_updated)):
                max_updated = updated

        if len(rows) < args.page_size:
            break
        offset += args.page_size

    next_cursor = max_updated or cursor
    out_state = {
        "cursor": next_cursor,
        "last_run": _now_iso(),
        "stats": {
            "scanned": scanned,
            "changed": changed,
            "upserted": upserted,
            "pages": pages,
            "dry_run": bool(args.dry_run),
            "full_reindex": bool(args.full_reindex),
        },
    }
    if not args.dry_run:
        _save_json(args.state_file, out_state)

    print(json.dumps(out_state, ensure_ascii=False, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Incremental sync: Anytype Local API -> Qdrant")
    ap.add_argument("--state-file", default="/app/data/anytype_sync_state.json")
    ap.add_argument("--page-size", type=int, default=50)
    ap.add_argument("--max-pages", type=int, default=40)
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
