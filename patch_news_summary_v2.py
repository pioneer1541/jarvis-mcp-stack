import os
import sys
from datetime import datetime

TARGET = "app.py"
MARK = "NEWS_SUMMARY_V2"

def read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def backup(p):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak.news_summary_v2." + ts
    with open(p, "rb") as src, open(bak, "wb") as dst:
        dst.write(src.read())
    return bak

def find_top_level_def(lines, name):
    needle = "def " + name + "("
    for i, ln in enumerate(lines):
        if ln.startswith(needle):
            return i
    return None

def find_block_end(lines, start_i):
    # end at next top-level "def " or "class " (col 0)
    for j in range(start_i + 1, len(lines)):
        if lines[j].startswith("def ") or lines[j].startswith("class "):
            return j
    return len(lines)

def replace_top_level_def(lines, name, new_block_lines):
    s = find_top_level_def(lines, name)
    if s is None:
        return None, None, None
    e = find_block_end(lines, s)
    out = lines[:s] + new_block_lines + lines[e:]
    return out, s, e

def patch_snippet_len(src_lines):
    # best-effort: replace "snippet = content_plain[:180]" style inside news_digest
    out = []
    in_news = False
    indent = ""
    replaced = False

    for ln in src_lines:
        if ln.startswith("def news_digest("):
            in_news = True
        if in_news and (ln.startswith("def ") or ln.startswith("class ")) and (not ln.startswith("def news_digest(")):
            in_news = False

        if in_news and (not replaced):
            # Look for assignment to snippet that slices content_plain
            # Examples we handle:
            #   snippet = (content_plain[:180] + "…") if len(content_plain) > 180 else content_plain
            #   snippet = content_plain[:180].strip()
            if ("snippet" in ln) and ("content_plain" in ln) and ("[:180]" in ln or "180" in ln) and ("=" in ln):
                # derive indentation from current line
                indent = ln.split("s", 1)[0]
                out.append(indent + "# " + MARK + "\n")
                out.append(indent + "sn_lim = int(os.environ.get(\"NEWS_SNIPPET_CHARS\") or \"320\")\n")
                out.append(indent + "if sn_lim < 60:\n")
                out.append(indent + "    sn_lim = 60\n")
                out.append(indent + "if len(content_plain) > sn_lim:\n")
                out.append(indent + "    snippet = content_plain[:sn_lim].rstrip() + \"…\"\n")
                out.append(indent + "else:\n")
                out.append(indent + "    snippet = content_plain\n")
                replaced = True
                continue

        out.append(ln)

    return out, replaced

def main():
    if not os.path.exists(TARGET):
        print("ERROR: not found:", TARGET)
        sys.exit(1)

    src = read_text(TARGET)
    if MARK in src:
        print("OK: already patched (marker found).")
        return

    lines = src.splitlines(True)

    # 1) Replace _news__voice_clip_snippet
    new_clip = []
    new_clip.append("def _news__voice_clip_snippet(s: str, max_len: int = 200) -> str:\n")
    new_clip.append("    \"\"\"Clip snippet for TTS.\n")
    new_clip.append("    Allow ellipsis endings (… or ...) rather than rejecting them.\n")
    new_clip.append("    \"\"\"\n")
    new_clip.append("    t = str(s or \"\").strip()\n")
    new_clip.append("    if not t:\n")
    new_clip.append("        return \"\"\n")
    new_clip.append("    # Normalize whitespace\n")
    new_clip.append("    t = \" \".join(t.split())\n")
    new_clip.append("    if max_len is None:\n")
    new_clip.append("        return t\n")
    new_clip.append("    try:\n")
    new_clip.append("        m = int(max_len)\n")
    new_clip.append("    except Exception:\n")
    new_clip.append("        m = 200\n")
    new_clip.append("    if m < 60:\n")
    new_clip.append("        m = 60\n")
    new_clip.append("    if len(t) <= m:\n")
    new_clip.append("        return t\n")
    new_clip.append("    return t[:m].rstrip() + \"…\"\n")
    new_clip.append("\n")

    lines, s1, e1 = replace_top_level_def(lines, "_news__voice_clip_snippet", new_clip)
    if lines is None:
        print("ERROR: cannot find top-level def _news__voice_clip_snippet")
        sys.exit(2)

    # 2) Replace _news__format_voice_miniflux
    new_fmt = []
    new_fmt.append("def _news__format_voice_miniflux(items: list, max_items: int = 5) -> str:\n")
    new_fmt.append("    \"\"\"Format news for voice output: title + summary (2 lines per item).\"\"\"\n")
    new_fmt.append("    its = items if isinstance(items, list) else []\n")
    new_fmt.append("    try:\n")
    new_fmt.append("        n = int(max_items)\n")
    new_fmt.append("    except Exception:\n")
    new_fmt.append("        n = 5\n")
    new_fmt.append("    if n <= 0:\n")
    new_fmt.append("        n = 5\n")
    new_fmt.append("    out_lines = []\n")
    new_fmt.append("    # per-item summary length for voice (TTS)\n")
    new_fmt.append("    try:\n")
    new_fmt.append("        sn_vo = int(os.environ.get(\"NEWS_VOICE_SNIP_LEN\") or \"200\")\n")
    new_fmt.append("    except Exception:\n")
    new_fmt.append("        sn_vo = 200\n")
    new_fmt.append("    if sn_vo < 80:\n")
    new_fmt.append("        sn_vo = 80\n")
    new_fmt.append("\n")
    new_fmt.append("    k = 0\n")
    new_fmt.append("    for it in its:\n")
    new_fmt.append("        if not isinstance(it, dict):\n")
    new_fmt.append("            continue\n")
    new_fmt.append("        if k >= n:\n")
    new_fmt.append("            break\n")
    new_fmt.append("        k += 1\n")
    new_fmt.append("        title = str(it.get(\"title_voice\") or it.get(\"title\") or \"\").strip()\n")
    new_fmt.append("        if not title:\n")
    new_fmt.append("            title = \"(no title)\"\n")
    new_fmt.append("        # choose best available summary\n")
    new_fmt.append("        sn = str(it.get(\"snippet\") or \"\").strip()\n")
    new_fmt.append("        if not sn:\n")
    new_fmt.append("            sn = str(it.get(\"content_plain\") or it.get(\"content\") or \"\").strip()\n")
    new_fmt.append("        sn = _news__voice_clip_snippet(sn, sn_vo) if sn else \"\"\n")
    new_fmt.append("        out_lines.append(str(k) + \") \" + title)\n")
    new_fmt.append("        if sn:\n")
    new_fmt.append("            out_lines.append(\"   \" + sn)\n")
    new_fmt.append("\n")
    new_fmt.append("    return \"\\n\".join(out_lines).strip()\n")
    new_fmt.append("\n")

    lines, s2, e2 = replace_top_level_def(lines, "_news__format_voice_miniflux", new_fmt)
    if lines is None:
        print("ERROR: cannot find top-level def _news__format_voice_miniflux")
        sys.exit(3)

    # 3) Patch snippet length inside news_digest
    lines, replaced = patch_snippet_len(lines)
    if not replaced:
        print("WARN: could not patch snippet length (no matching line found). Voice summary will still work using existing snippet/content_plain.")
        # continue anyway

    new_src = "".join(lines)

    # Add marker near top (best effort)
    if MARK not in new_src:
        new_src = "# " + MARK + "\n" + new_src

    bak = backup(TARGET)
    write_text(TARGET, new_src)
    print("OK: patched", TARGET)
    print("Backup:", bak)

if __name__ == "__main__":
    main()
