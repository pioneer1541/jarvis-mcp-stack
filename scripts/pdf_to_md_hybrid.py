#!/usr/bin/env python3
"""
Hybrid PDF -> Markdown extractor.

Per page:
- Try PDF text layer first (fast/accurate for native PDFs).
- If extracted text is too short, fallback to a vision model (qwen3-vl) via Ollama.
  If VL output is still too short, retry with a bigger VL model.
- Optionally post-clean with a text LLM to output Markdown only.

This is intended to generate RAG-friendly Markdown artifacts that can then be
ingested into Qdrant by existing scripts.
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

try:
    import pypdfium2 as pdfium  # type: ignore
except Exception as e:  # pragma: no cover
    pdfium = None


def _b64_file(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _ollama_chat(ollama_base: str, model: str, prompt: str, image_b64: str, timeout_sec: float) -> Dict:
    url = ollama_base.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": "Extract text from a PDF page image. Output only extracted content, no explanations.",
            },
            {
                "role": "user",
                "content": prompt,
                "images": [image_b64],
            },
        ],
        "options": {
            "temperature": 0.1,
            "top_p": 0.9,
        },
    }
    r = requests.post(url, json=payload, timeout=timeout_sec)
    if int(getattr(r, "status_code", 0) or 0) >= 400:
        raise RuntimeError(f"ollama_chat_http_{int(r.status_code)}:{str(getattr(r, 'text', ''))[:200]}")
    return r.json() if hasattr(r, "json") else {}


def _ollama_generate(ollama_base: str, model: str, prompt: str, timeout_sec: float) -> str:
    url = ollama_base.rstrip("/") + "/api/generate"
    payload = {
        "model": model,
        "stream": False,
        "prompt": prompt,
        "options": {
            "temperature": 0.1,
            "top_p": 0.9,
        },
    }
    r = requests.post(url, json=payload, timeout=timeout_sec)
    if int(getattr(r, "status_code", 0) or 0) >= 400:
        raise RuntimeError(f"ollama_generate_http_{int(r.status_code)}:{int(r.status_code)}:{str(getattr(r, 'text', ''))[:200]}")
    obj = r.json() if hasattr(r, "json") else {}
    return str(obj.get("response") or "")


def _vl_text(resp: Dict) -> str:
    msg = resp.get("message") if isinstance(resp, dict) else None
    msg = msg if isinstance(msg, dict) else {}
    # qwen3-vl on some Ollama versions puts the actual output in `thinking`.
    content = str(msg.get("content") or "").strip()
    if content:
        return content
    return str(msg.get("thinking") or "").strip()


def _scrub_vl(raw: str) -> str:
    s = str(raw or "").strip()
    s = re.sub(r"^\s*(Sure\.|Okay\.|当然|好的)\s*\n", "", s)
    return s.strip()


def _clean_textlayer_to_markdown(text: str) -> str:
    # Minimal normalization for RAG: stable whitespace, keep existing line breaks.
    s = (text or "").replace("\r", "\n")
    lines = [ln.rstrip() for ln in s.split("\n")]

    out: List[str] = []
    prev_blank = True
    for ln in lines:
        ln = ln.strip()
        if not ln:
            if not prev_blank:
                out.append("")
            prev_blank = True
            continue

        # Light heading heuristics
        if re.match(r"^\d+\.\s+[A-Z]", ln):
            out.append(f"### {ln}")
        elif ln.isupper() and 3 <= len(ln) <= 48:
            out.append(f"### {ln}")
        else:
            out.append(ln)
        prev_blank = False

    # Collapse excessive blank lines
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out).strip()


def _parse_pages(pages: str, total_pages: int) -> List[int]:
    p = (pages or "").strip().lower()
    if not p:
        return list(range(1, total_pages + 1))
    if p in ("all", "*"):
        return list(range(1, total_pages + 1))
    m = re.match(r"^(\d+)\s*-\s*(\d+)$", p)
    if m:
        a = int(m.group(1))
        b = int(m.group(2))
        if a < 1 or b < 1:
            raise ValueError("pages must be >= 1")
        if b < a:
            a, b = b, a
        return [i for i in range(a, min(b, total_pages) + 1)]
    parts = []
    for part in re.split(r"[,\s]+", p):
        if not part:
            continue
        parts.append(int(part))
    out = [i for i in parts if 1 <= i <= total_pages]
    if not out:
        raise ValueError("no valid pages selected")
    return out


def _default_out_dir() -> str:
    # Prefer an explicit env var. Otherwise, default to a "processed_md" folder alongside export dir.
    v = str(os.environ.get("PDF_MD_OUT_DIR") or "").strip()
    if v:
        return v
    export_dir = str(os.environ.get("ANYTYPE_EXPORT_DIR") or "").strip()
    if export_dir:
        return str(Path(export_dir) / "processed_md")
    return "/mnt/nas/anytype_export/processed_md"


def _pages_tag(pages: str) -> str:
    p = str(pages or "").strip().lower()
    if not p:
        return "all"
    if p in ("*", "all"):
        return "all"
    p = p.replace(" ", "").replace(",", "_").replace(";", "_")
    p = p.replace("*", "all")
    p = re.sub(r"[^0-9a-zA-Z_\\-]", "", p)
    if p and p[0].isdigit():
        return "p" + p
    return p or "all"


def run(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", default="", help="output .md path (optional). If empty, uses --out-dir.")
    ap.add_argument("--out-dir", default=_default_out_dir(), help="output directory when --out is empty")
    ap.add_argument("--pages", default="1-10", help="e.g. 1-10, 3,5,7, or all")
    ap.add_argument("--min-text-chars", type=int, default=80, help="below this per-page, fallback to VL")
    ap.add_argument("--ollama", default=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    ap.add_argument("--vl", default="qwen3-vl:2b")
    ap.add_argument("--vl-fallback", default="qwen3-vl:8b")
    ap.add_argument("--clean", default="qwen3:8b", help="text model to post-clean VL output (Markdown only)")
    ap.add_argument("--render-scale", type=float, default=2.0)
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--tmp-dir", default="/tmp/pdf_to_md_hybrid")
    args = ap.parse_args(argv)

    if pdfium is None:
        print("ERROR: pypdfium2 not available in this environment", file=sys.stderr)
        return 2

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"ERROR: pdf not found: {pdf_path}", file=sys.stderr)
        return 2

    out_arg = str(args.out or "").strip()
    if out_arg:
        out_path = Path(out_arg)
    else:
        out_dir = Path(str(args.out_dir or "").strip() or _default_out_dir())
        out_name = f"{pdf_path.stem}.hybrid_{_pages_tag(args.pages)}.md"
        out_path = out_dir / out_name
    out_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_dir = Path(args.tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    doc = pdfium.PdfDocument(str(pdf_path))
    total_pages = len(doc)
    selected = _parse_pages(args.pages, total_pages)

    parts: List[str] = []
    for page_no in selected:
        page = doc[page_no - 1]

        # Text layer attempt
        text = ""
        try:
            tp = page.get_textpage()
            text = str(tp.get_text_range() or "")
        except Exception:
            text = ""

        use_vl = len(text.strip()) < int(args.min_text_chars)

        if not use_vl:
            body = _clean_textlayer_to_markdown(text)
            parts.append(f"## Page {page_no}\n\n{body}".strip())
            continue

        # VL fallback (render page to image)
        img_path = tmp_dir / f"{pdf_path.stem}.p{page_no}.jpg"
        try:
            pil = page.render(scale=float(args.render_scale)).to_pil()
            pil.save(img_path, "JPEG", quality=92)
        except Exception as e:
            parts.append(f"## Page {page_no}\n\n[[render_failed: {e}]]".strip())
            continue

        prompt = (
            "Extract all visible text and structure as Markdown. Preserve headings, lists, and tables. "
            "If something is unreadable, write [[illegible]]. Output only the content."
        )

        raw = ""
        try:
            resp = _ollama_chat(args.ollama, args.vl, prompt, _b64_file(img_path), args.timeout)
            raw = _scrub_vl(_vl_text(resp))
        except Exception:
            raw = ""

        if len(raw.strip()) < int(args.min_text_chars) and args.vl_fallback:
            try:
                resp = _ollama_chat(args.ollama, args.vl_fallback, prompt, _b64_file(img_path), args.timeout)
                raw2 = _scrub_vl(_vl_text(resp))
                if len(raw2.strip()) > len(raw.strip()):
                    raw = raw2
            except Exception:
                pass

        # Post-clean to "Markdown only"
        clean_prompt = (
            "Rewrite the following noisy extraction into clean Markdown ONLY.\n"
            f"Rules:\n- Output only Markdown, no commentary.\n- Start with: ## Page {page_no}\n"
            "- Do not invent missing content; use [[illegible]] where needed.\n\n"
            f"Source: {pdf_path.name}\n\nRAW:\n{raw}\n"
        )
        try:
            md = _ollama_generate(args.ollama, args.clean, clean_prompt, args.timeout).strip()
        except Exception:
            md = f"## Page {page_no}\n\n{raw}".strip()

        parts.append(md.strip())

    header = (
        f"<!-- generated_by: pdf_to_md_hybrid.py -->\n"
        f"<!-- source_pdf: {pdf_path} -->\n"
        f"<!-- pages: {args.pages} -->\n"
    )
    out_text = header + "\n\n".join([p for p in parts if str(p or "").strip()]) + "\n"
    out_path.write_text(out_text, encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
