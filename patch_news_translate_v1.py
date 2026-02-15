import io
import os
import sys

REPL_BLOCK = r'''# ---- News voice + optional EN->ZH translation (Ollama) ----
_NEWS_TR_CACHE = {}  # key -> {"ts": int, "title": str, "snippet": str}

def _news__tr__cache_get(key: str, ttl_sec: int):
    try:
        import time
        now = int(time.time())
        it = _NEWS_TR_CACHE.get(key)
        if not it:
            return None
        ts = int(it.get("ts") or 0)
        if (now - ts) > int(ttl_sec):
            return None
        return it
    except Exception:
        return None

def _news__tr__cache_put(key: str, title_zh: str, snippet_zh: str):
    try:
        import time
        _NEWS_TR_CACHE[key] = {
            "ts": int(time.time()),
            "title": (title_zh or "").strip(),
            "snippet": (snippet_zh or "").strip(),
        }
    except Exception:
        return

def _news__translate_batch_to_zh(pairs: list, model: str = "", base_url: str = "", timeout_sec: int = 12) -> list:
    """
    pairs: [{"title": "...", "snippet": "..."}]
    returns: [{"title": "...", "snippet": "..."}] (Chinese, same length as input; may contain empty strings on failure)
    """
    out = []
    try:
        if not isinstance(pairs, list) or (len(pairs) == 0):
            return out

        import json
        import urllib.request
        import urllib.error
        import hashlib

        bu = (base_url or os.environ.get("OLLAMA_BASE_URL") or "http://192.168.1.162:11434").strip()
        if not bu:
            bu = "http://192.168.1.162:11434"
        mdl = (model or os.environ.get("NEWS_TRANSLATE_MODEL") or os.environ.get("OLLAMA_TRANSLATE_MODEL") or "qwen3:1.7b").strip()
        if not mdl:
            mdl = "qwen3:1.7b"

        # Build prompt
        sys_msg = (
            "你是中文新闻播报翻译助手。把英文新闻标题和摘要翻译成适合中文语音播报的自然中文。"
            "要求：简洁、口语化、不要加链接、不要加多余解释、不要输出英文。"
            "每条输出一行，严格保持条目数量一致。格式必须为："
            "N) <中文标题> ||| <中文摘要> 。摘要可为空但分隔符必须保留。"
        )

        lines = []
        i = 1
        for p in pairs:
            if not isinstance(p, dict):
                p = {}
            t = str(p.get("title") or "").strip()
            s = str(p.get("snippet") or "").strip()
            # clamp input to reduce latency
            if len(t) > 220:
                t = t[:220].rstrip()
            if len(s) > 300:
                s = s[:300].rstrip()
            lines.append("{0})".format(i))
            lines.append("TITLE: {0}".format(t))
            lines.append("SNIP: {0}".format(s))
            lines.append("")
            i += 1
        user_msg = "请翻译以下条目：\n" + "\n".join(lines)

        payload = {
            "model": mdl,
            "stream": False,
            "messages": [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg},
            ],
            "options": {
                "temperature": 0.2
            },
        }

        url = bu.rstrip("/") + "/api/chat"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
                raw = resp.read().decode("utf-8", "ignore")
        except Exception as e:
            # On failure, return empty placeholders
            for _ in pairs:
                out.append({"title": "", "snippet": ""})
            return out

        try:
            obj = json.loads(raw)
        except Exception:
            obj = {}

        content = ""
        try:
            content = str(((obj.get("message") or {}).get("content")) or "").strip()
        except Exception:
            content = ""

        # Parse lines "N) title ||| snippet"
        # Make sure we always return same length.
        parsed = []
        if content:
            for ln in content.splitlines():
                x = (ln or "").strip()
                if not x:
                    continue
                parsed.append(x)

        # Build mapping by leading "N)"
        got = {}
        for x in parsed:
            # accept formats like "1) ..." or "1） ..."
            m = None
            try:
                import re
                m = re.match(r"^\s*(\d{1,2})\s*[)\）]\s*(.*)$", x)
            except Exception:
                m = None
            if not m:
                continue
            try:
                n = int(m.group(1))
            except Exception:
                continue
            rest = (m.group(2) or "").strip()
            title_zh = rest
            snip_zh = ""
            if "|||" in rest:
                parts = rest.split("|||", 1)
                title_zh = (parts[0] or "").strip()
                snip_zh = (parts[1] or "").strip()
            got[n] = {"title": title_zh, "snippet": snip_zh}

        for idx in range(1, len(pairs) + 1):
            it = got.get(idx) or {"title": "", "snippet": ""}
            out.append({"title": (it.get("title") or "").strip(), "snippet": (it.get("snippet") or "").strip()})

        return out
    except Exception:
        for _ in (pairs or []):
            out.append({"title": "", "snippet": ""})
        return out


def _news__format_voice_miniflux(items: list, limit: int = 5, prefer_lang: str = "zh") -> str:
    """
    Voice-friendly news lines:
    - No URL
    - Short snippet
    - Keep source + published time when available
    - When prefer_lang=zh: translate EN title/snippet to Chinese for TTS via local Ollama (batch + cache)
    """
    try:
        lim = int(limit)
    except Exception:
        lim = 5
    if lim < 1:
        lim = 1
    if lim > 10:
        lim = 10

    it = items or []
    if (not isinstance(it, list)) or (len(it) == 0):
        return ""

    prefer = (prefer_lang or "zh").strip().lower()
    if prefer not in ["zh", "en"]:
        prefer = "zh"

    enable_tr = str(os.environ.get("NEWS_TRANSLATE_ENABLE") or "1").strip()
    do_tr = (prefer == "zh") and (enable_tr not in ["0", "false", "False", "off", "OFF"])

    try:
        ttl = int(os.environ.get("NEWS_TRANSLATE_CACHE_TTL_SEC") or "86400")
    except Exception:
        ttl = 86400
    try:
        tosec = float(os.environ.get("NEWS_TRANSLATE_TIMEOUT_SEC") or "12")
    except Exception:
        tosec = 12.0

    # Collect EN items needing translation
    idx_list = []
    pairs = []
    key_list = []

    if do_tr:
        for j, x in enumerate(it):
            if len(idx_list) >= lim:
                break
            if not isinstance(x, dict):
                continue
            title = str(x.get("title") or "").strip()
            if not title:
                continue
            is_zh = bool(x.get("is_zh"))
            if is_zh:
                continue
            sn = str(x.get("snippet") or "").strip()

            # cache key
            try:
                import hashlib
                h = hashlib.sha1()
                h.update((title + "\n" + sn).encode("utf-8", "ignore"))
                k = h.hexdigest()
            except Exception:
                k = title + "\n" + sn

            hit = _news__tr__cache_get(k, ttl)
            if hit:
                continue
            idx_list.append(j)
            key_list.append(k)
            pairs.append({"title": title, "snippet": sn})

        if pairs:
            tr = _news__translate_batch_to_zh(pairs, model=(os.environ.get("NEWS_TRANSLATE_MODEL") or "qwen3:1.7b"), base_url=(os.environ.get("OLLAMA_BASE_URL") or "http://192.168.1.162:11434"), timeout_sec=tosec)
            # store cache
            try:
                for kk, rr in zip(key_list, tr):
                    if not isinstance(rr, dict):
                        continue
                    _news__tr__cache_put(kk, rr.get("title") or "", rr.get("snippet") or "")
            except Exception:
                pass

    out = []
    idx = 1
    for x in it:
        if idx > lim:
            break
        if not isinstance(x, dict):
            continue

        title = str(x.get("title") or "").strip()
        if not title:
            continue

        src = str(x.get("source") or "").strip()
        pa = str(x.get("published_at") or "").strip()
        sn = str(x.get("snippet") or "").strip()

        # translate if needed (prefer zh)
        if do_tr and (not bool(x.get("is_zh"))):
            try:
                import hashlib
                h = hashlib.sha1()
                h.update((title + "\n" + sn).encode("utf-8", "ignore"))
                k = h.hexdigest()
            except Exception:
                k = title + "\n" + sn
            hit = _news__tr__cache_get(k, ttl)
            if hit:
                t2 = str(hit.get("title") or "").strip()
                s2 = str(hit.get("snippet") or "").strip()
                if t2:
                    title = t2
                if s2:
                    sn = s2

        # tighten snippet for TTS
        if len(sn) > 90:
            sn = sn[:90].rstrip() + "…"

        line = str(idx) + ") " + title
        meta = []
        if src:
            meta.append(src)
        if pa:
            meta.append(pa)
        if meta:
            line = line + "（" + " | ".join(meta) + "）"
        out.append(line)
        if sn:
            out.append("   " + sn)
        idx += 1

    return "\n".join(out).strip()
'''

def main():
    p = "app.py"
    if not os.path.exists(p):
        print("ERROR: app.py not found in current directory")
        sys.exit(1)

    with io.open(p, "r", encoding="utf-8") as f:
        s = f.read()

    # find the first occurrence of the formatter function at file top
    start = s.find("def _news__format_voice_miniflux(")
    if start < 0:
        print("ERROR: cannot find def _news__format_voice_miniflux(")
        sys.exit(1)

    # end is right before the first "\nimport os" after it (current file structure)
    end = s.find("\n\nimport os", start)
    if end < 0:
        end = s.find("\nimport os", start)
    if end < 0:
        print("ERROR: cannot find import os after the function block; abort to avoid corrupting file")
        sys.exit(1)

    new_s = s[:start] + REPL_BLOCK + s[end:]

    with io.open(p, "w", encoding="utf-8") as f:
        f.write(new_s)

    print("OK: patched _news__format_voice_miniflux with Ollama translate + cache")

if __name__ == "__main__":
    main()
