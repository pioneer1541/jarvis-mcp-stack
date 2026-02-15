#!/usr/bin/env python3
# patch_news_summary_v1.py
# Purpose:
# - News voice output: include short summary snippet (from Miniflux entry content) in final_voice
# - Keep tool return as plain text (already handled by route_request returning str)
# - No translation changes here (translation is controlled elsewhere / env)
#
# Safety:
# - Creates a backup: app.py.bak.news_summary_v1.<timestamp>
# - Avoids fragile regex anchors; replaces whole def blocks by locating top-level def boundaries.

import os
import re
import shutil
from datetime import datetime

APP_PATH = os.environ.get("APP_PATH") or "app.py"

NEW_NEWS_VOICE_CLIP = """def _news__voice_clip_snippet(sn: str, prefer: str = "zh", max_len: int = 160) -> str:
    \"\"\"Make snippet TTS-friendly.

    Notes:
    - Keep plain text only (no links, no JSON).
    - If the source snippet ends with ellipsis (.../…/⋯), we *keep* it but strip the ellipsis so
      HA/TTS won't treat it as a hard truncation marker.
    - Prefer cutting at sentence punctuation.
    \"\"\"
    try:
        s = (sn or \"\").strip()
        if not s:
            return \"\"

        # Normalize whitespace
        try:
            s = \" \".join(s.split())
        except Exception:
            s = (sn or \"\").strip()

        # Strip trailing ellipsis markers (keep content)
        while True:
            if s.endswith(\"...\") or s.endswith(\"……\") or s.endswith(\"…\") or s.endswith(\"⋯\"):
                s = s.rstrip(\".⋯…\").strip()
                continue
            break

        try:
            ml = int(max_len)
        except Exception:
            ml = 160
        if ml < 80:
            ml = 80
        if ml > 500:
            ml = 500

        if len(s) <= ml:
            return s

        cut = s[:ml]

        # Prefer last sentence-ending punctuation within cut
        seps = [\"。\", \"！\", \"？\", \".\", \"!\", \"?\"]
        best = -1
        for ch in seps:
            pos = cut.rfind(ch)
            if pos > best:
                best = pos
        if best >= 30:
            cut = cut[:best+1].strip()
            return cut

        # Otherwise try comma/semicolon-ish boundary
        seps2 = [\"，\", \",\", \"；\", \";\", \":\", \"：\"]
        best2 = -1
        for ch in seps2:
            pos = cut.rfind(ch)
            if pos > best2:
                best2 = pos
        if best2 >= 35:
            cut = cut[:best2].strip()
        else:
            sp = cut.rfind(\" \")
            if sp >= 35:
                cut = cut[:sp].strip()

        if not cut:
            return \"\"

        # End with a full stop for better TTS cadence
        if not (cut.endswith(\"。\") or cut.endswith(\"！\") or cut.endswith(\"？\") or cut.endswith(\".\") or cut.endswith(\"!\") or cut.endswith(\"?\")):
            # If it already contains many CJK chars, use Chinese period; else use dot.
            try:
                cjk_cnt = 0
                for ch in cut:
                    oc = ord(ch)
                    if (0x4E00 <= oc <= 0x9FFF) or (0x3400 <= oc <= 0x9FFF) or (0x20000 <= oc <= 0x2A6DF):
                        cjk_cnt += 1
                cut = cut + (\"。\" if cjk_cnt >= 6 else \".\")
            except Exception:
                cut = cut + \"。\"

        return cut
    except Exception:
        return \"\"
"""

NEW_NEWS_FORMAT_VOICE = """def _news__format_voice_miniflux(items: list, limit: int = 5) -> str:
    \"\"\"Voice-friendly news lines (title + short summary).

    - Plain text only (no source/time/URL).
    - Prefer title_voice when available.
    - Also attach snippet/content summary when available.
    - Each item outputs 1-2 lines:
        N) <TITLE>
           <SUMMARY>
    \"\"\"
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
        return \"\"

    try:
        sn_lim = int(os.environ.get(\"NEWS_VOICE_SNIP_LEN\") or \"200\")
    except Exception:
        sn_lim = 200
    if sn_lim < 120:
        sn_lim = 120
    if sn_lim > 600:
        sn_lim = 600

    def _clean_title(s: str) -> str:
        t = (s or \"\").strip()
        if not t:
            return \"\"
        try:
            t = re.sub(r\"\\s+\", \" \", t).strip()
        except Exception:
            t = (s or \"\").strip()

        # Remove EN tail: -/–/— video, (video), [video]
        try:
            t = re.sub(r\"\\s*[\\-\\u2013\\u2014\\u2212]+\\s*video\\s*$\", \"\", t, flags=re.I).strip()
            t = re.sub(r\"\\s*[\\(\\[]\\s*video\\s*[\\)\\]]\\s*$\", \"\", t, flags=re.I).strip()
        except Exception:
            pass

        # Remove CN tail: -/–/—/—— 视频, （视频）,【视频】,(视频)
        try:
            t = re.sub(r\"\\s*——\\s*视频\\s*$\", \"\", t).strip()
            t = re.sub(r\"\\s*[\\-\\u2013\\u2014\\u2212]+\\s*视频\\s*$\", \"\", t).strip()
            t = re.sub(r\"\\s*（\\s*视频\\s*）\\s*$\", \"\", t).strip()
            t = re.sub(r\"\\s*【\\s*视频\\s*】\\s*$\", \"\", t).strip()
            t = re.sub(r\"\\s*\\(\\s*视频\\s*\\)\\s*$\", \"\", t).strip()
        except Exception:
            pass

        return (t or \"\").strip()

    out = []
    idx = 1
    for x in it:
        if idx > lim:
            break
        if not isinstance(x, dict):
            continue

        title = str(x.get(\"title_voice\") or x.get(\"title_zh\") or x.get(\"title\") or \"\").strip()
        title = _clean_title(title)
        if not title:
            continue
        if len(title) > 140:
            title = title[:140].rstrip() + \"…\"

        # Prefer snippet_voice; fallback to snippet/content_plain
        sn = str(x.get(\"snippet_voice\") or x.get(\"snippet\") or x.get(\"content_plain\") or \"\").strip()
        sn2 = \"\"
        if sn:
            sn2 = _news__voice_clip_snippet(sn, prefer=\"zh\", max_len=sn_lim)

        if sn2:
            out.append(str(idx) + \") \" + title)
            out.append(\"   \" + sn2)
        else:
            out.append(str(idx) + \") \" + title)

        idx += 1

    return \"\\n\".join(out).strip()
"""

def _read_lines(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return f.readlines()

def _write_lines(path: str, lines):
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(lines))

def _find_def_block(lines, def_name):
    pat = re.compile(r"^def\\s+" + re.escape(def_name) + r"\\s*\\(")
    start = None
    for i, l in enumerate(lines):
        if pat.match(l):
            start = i
            break
    if start is None:
        raise RuntimeError("def not found: " + def_name)

    end = len(lines)
    for j in range(start + 1, len(lines)):
        if (re.match(r"^(def|class)\\s+\\w+", lines[j]) or re.match(r"^@", lines[j])) and (not lines[j].startswith(" ")):
            end = j
            break
    return start, end

def _replace_block(lines, start, end, new_block_text):
    nb = new_block_text.splitlines(True)
    return lines[:start] + nb + lines[end:]

def _patch_snippet_truncation(lines):
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if ("snippet = content_plain" in line) and (line.lstrip().startswith("snippet =")):
            indent = line.split("snippet", 1)[0]
            out.append(line)

            j = i + 1
            if j < len(lines) and ("if len(snippet) > 180" in lines[j]):
                # skip the old if-block (if line + one body line)
                j2 = j + 2
                block = [
                    indent + "try:\\n",
                    indent + "    sn_lim = int(os.environ.get(\\"NEWS_SNIPPET_CHARS\\") or \\"320\\")\\n",
                    indent + "except Exception:\\n",
                    indent + "    sn_lim = 320\\n",
                    indent + "if sn_lim < 120:\\n",
                    indent + "    sn_lim = 120\\n",
                    indent + "if sn_lim > 800:\\n",
                    indent + "    sn_lim = 800\\n",
                    indent + "if len(snippet) > sn_lim:\\n",
                    indent + "    snippet = snippet[:sn_lim].rstrip() + \\"…\\"\\n",
                ]
                out.extend(block)
                i = j2
                continue
        out.append(line)
        i += 1
    return out

def main():
    if not os.path.exists(APP_PATH):
        raise SystemExit("app.py not found at: " + APP_PATH)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = "app.py.bak.news_summary_v1." + ts
    shutil.copy2(APP_PATH, bak)
    print("Backup:", bak)

    lines = _read_lines(APP_PATH)

    # Replace 2 functions
    s1, e1 = _find_def_block(lines, "_news__voice_clip_snippet")
    lines = _replace_block(lines, s1, e1, NEW_NEWS_VOICE_CLIP)

    s2, e2 = _find_def_block(lines, "_news__format_voice_miniflux")
    lines = _replace_block(lines, s2, e2, NEW_NEWS_FORMAT_VOICE)

    # Patch snippet truncation in news_digest loop
    lines = _patch_snippet_truncation(lines)

    _write_lines(APP_PATH, lines)
    print("Patched:", APP_PATH)
    print("Next: python3 -m py_compile app.py")

if __name__ == "__main__":
    main()

