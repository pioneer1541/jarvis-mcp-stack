import re
import shutil
from datetime import datetime

APP = "app.py"

def _backup():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = "app.py.bak.news_p1p3_voice_route_v1_" + ts
    shutil.copyfile(APP, bak)
    return bak

def _read():
    with open(APP, "r", encoding="utf-8") as f:
        return f.read()

def _write(s):
    with open(APP, "w", encoding="utf-8") as f:
        f.write(s)

def _ensure_voice_helper(src):
    if "_news__format_voice_miniflux" in src:
        return src, False

    helper = r'''
def _news__format_voice_miniflux(items: list, limit: int = 5) -> str:
    """
    Voice-friendly news lines:
    - No URL
    - Short snippet
    - Keep source + published time when available
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
'''.lstrip("\n")

    # Insert helper right after _news__format_final() if exists; otherwise prepend near top.
    m = re.search(r"^def\s+_news__format_final\s*\(.*?\):[^\n]*\n", src, flags=re.MULTILINE)
    if not m:
        return helper + "\n\n" + src, True

    # find end of _news__format_final block by next top-level "def " after it
    start = m.start()
    m2 = re.search(r"^def\s+", src[m.end():], flags=re.MULTILINE)
    if not m2:
        insert_pos = len(src)
    else:
        insert_pos = m.end() + m2.start()

    out = src[:insert_pos] + "\n\n" + helper + "\n\n" + src[insert_pos:]
    return out, True

def _patch_news_digest_success_return(src):
    # Find news_digest function block
    m0 = re.search(r"^def\s+news_digest\s*\(", src, flags=re.MULTILINE)
    if not m0:
        raise RuntimeError("cannot find def news_digest(")

    # find end of function block: next top-level def after news_digest
    m1 = re.search(r"^def\s+|^@mcp\.tool", src[m0.end():], flags=re.MULTILINE)
    if not m1:
        end = len(src)
    else:
        end = m0.end() + m1.start()

    head = src[:m0.start()]
    block = src[m0.start():end]
    tail = src[end:]

    # Find ALL "return { ... }" blocks inside news_digest, pick the last one that looks like success return
    pat = re.compile(r"(?ms)^(?P<ind>[ \t]+)return\s*\{\s*\n(?P<body>.*?)(?P=ind)\}\s*$")
    matches = list(pat.finditer(block))
    if not matches:
        # nothing to patch
        return src, False

    chosen = None
    for mm in matches:
        txt = mm.group(0)
        if '"ok"' in txt and "True" in txt and '"items"' in txt and '"final"' in txt:
            chosen = mm
    if chosen is None:
        return src, False

    ind = chosen.group("ind")
    ret_dict_txt = chosen.group(0)

    # Transform:
    #   return { ... }
    # into:
    #   ret = { ... }
    #   if ("final_voice" not in ret) or (not str(ret.get("final_voice") or "").strip()):
    #       ret["final_voice"] = _news__format_voice_miniflux(ret.get("items") or [], ret.get("limit") or 5)
    #   return ret
    new_txt = ret_dict_txt.replace(ind + "return {", ind + "ret = {", 1)
    new_txt = new_txt + "\n" + ind + 'if ("final_voice" not in ret) or (not str(ret.get("final_voice") or "").strip()):' + "\n"
    new_txt = new_txt + ind + '    ret["final_voice"] = _news__format_voice_miniflux(ret.get("items") or [], ret.get("limit") or 5)' + "\n"
    new_txt = new_txt + ind + "return ret"

    block2 = block[:chosen.start()] + new_txt + block[chosen.end():]
    return head + block2 + tail, True

def _patch_route_request_voice_prefer(src):
    # Patch both news branches inside route_request:
    # 1) _news__is_query(...) branch (older one) -> add limit extract + prefer final_voice
    # 2) _is_news_query(...) branch -> prefer final_voice

    # (A) Replace rrn call that hardcodes limit=5 and user_text=""
    pat_call = re.compile(
        r'^(?P<ind>[ \t]+)rrn\s*=\s*news_digest\(\s*category\s*=\s*cat\s*,\s*limit\s*=\s*5\s*,\s*time_range\s*=\s*tr\s*,\s*prefer_lang\s*=\s*"zh"\s*,\s*user_text\s*=\s*""\s*\)\s*$',
        flags=re.MULTILINE
    )
    src2, n1 = pat_call.subn(
        lambda m: (
            m.group("ind") + "lim = _news__extract_limit(user_text, 5)\n" +
            m.group("ind") + "rrn = news_digest(category=cat, limit=lim, time_range=tr, prefer_lang=\"zh\", user_text=user_text)"
        ),
        src
    )

    # (A2) Replace return line using rrn.get("final") -> prefer final_voice
    pat_ret1 = re.compile(
        r'^(?P<ind>[ \t]+)return\s*\{\s*"ok"\s*:\s*True\s*,\s*"route_type"\s*:\s*"semi_structured_news"\s*,\s*"final"\s*:\s*rrn\.get\("final"\)\s*,\s*"data"\s*:\s*rrn\s*\}\s*$',
        flags=re.MULTILINE
    )
    src3, n2 = pat_ret1.subn(
        lambda m: (
            m.group("ind") + 'final = rrn.get("final_voice") or rrn.get("final") or ""\n' +
            m.group("ind") + 'return {"ok": True, "route_type": "semi_structured_news", "final": final, "data": rrn}'
        ),
        src2
    )

    # (B) In the newer branch: make the one-line final prefer final_voice
    pat_final = re.compile(
        r'^(?P<ind>[ \t]+)final\s*=\s*\(data\.get\("final"\)\s*or\s*""\)\s*if\s*isinstance\(data,\s*dict\)\s*else\s*""\s*$',
        flags=re.MULTILINE
    )
    src4, n3 = pat_final.subn(
        lambda m: m.group("ind") + 'final = (data.get("final_voice") or data.get("final") or "") if isinstance(data, dict) else ""',
        src3
    )

    # (B2) In the newer branch: pass prefer_lang + user_text into news_digest call if it lacks them (best-effort)
    pat_call2 = re.compile(
        r'^(?P<ind>[ \t]+)data\s*=\s*news_digest\(\s*category\s*=\s*cat\s*,\s*time_range\s*=\s*tr\s*,\s*limit\s*=\s*lim\s*\)\s*$',
        flags=re.MULTILINE
    )
    src5, n4 = pat_call2.subn(
        lambda m: m.group("ind") + 'data = news_digest(category=cat, time_range=tr, limit=lim, prefer_lang="zh", user_text=user_text)',
        src4
    )

    changed = (n1 + n2 + n3 + n4) > 0
    return src5, changed

def main():
    bak = _backup()
    src = _read()

    src, c1 = _ensure_voice_helper(src)
    src, c2 = _patch_news_digest_success_return(src)
    src, c3 = _patch_route_request_voice_prefer(src)

    _write(src)
    print("Backup:", bak)
    print("Changes:", {
        "add_voice_helper": c1,
        "news_digest_success_return": c2,
        "route_request_prefer_voice": c3,
    })

if __name__ == "__main__":
    main()
