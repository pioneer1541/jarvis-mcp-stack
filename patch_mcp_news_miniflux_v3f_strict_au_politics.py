#!/usr/bin/env python3
import os
import re
from datetime import datetime

def _read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def _write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def _backup(path, src):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path + ".bak.news_miniflux_v3f_" + ts
    _write(bak, src)
    return bak

def main():
    path = "app.py"
    if not os.path.exists(path):
        raise SystemExit("app.py not found")

    src = _read(path)

    # scope to Miniflux news_digest block
    marker = 'description="(Tool) News digest via Miniflux (RSS).'
    i0 = src.find(marker)
    if i0 < 0:
        raise SystemExit("cannot find Miniflux news_digest marker")

    end_candidates = []
    j1 = src.find("def news_digest_legacy_fn_1", i0)
    if j1 > 0:
        end_candidates.append(j1)
    j2 = src.find("# NEWS_DIGEST_V3_END", i0)
    if j2 > 0:
        end_candidates.append(j2)
    if not end_candidates:
        raise SystemExit("cannot find end boundary for Miniflux news_digest block")
    i1 = min(end_candidates)

    block = src[i0:i1]

    # Insert STRICT set right after wl/bl definition (near lines you pasted)
    anchor = 'bl = cfg.get("blacklist") or []'
    p = block.find(anchor)
    if p < 0:
        raise SystemExit("cannot find wl/bl anchor in news_digest block")

    # find line end
    p_line_end = block.find("\n", p)
    if p_line_end < 0:
        raise SystemExit("unexpected: no newline after bl definition")

    # detect indentation for this section from the anchor line
    line_start = block.rfind("\n", 0, p) + 1
    indent = ""
    while line_start + len(indent) < len(block) and block[line_start + len(indent)] in (" ", "\t"):
        indent += block[line_start + len(indent)]

    strict_line = indent + 'STRICT_WL_CATS = set(["au_politics"])' + "\n"
    require_line = indent + "require_wl = True if (key in STRICT_WL_CATS) else False" + "\n"

    if "STRICT_WL_CATS" in block:
        # already patched
        out_block = block
    else:
        out_block = block[:p_line_end+1] + strict_line + require_line + block[p_line_end+1:]

    # Now ensure later logic uses require_wl when filtering.
    # We patch the specific if-statement you grepped earlier:
    # if require_wl and (not _passes_whitelist(it)):
    # In case it's missing, we insert a guard in the loop where items are picked.
    if "if require_wl and (not _passes_whitelist(it))" not in out_block:
        # Try to find the first occurrence of whitelist check without require_wl and rewrite it safely.
        # Common pattern: if not _passes_whitelist(it):
        out_block2 = re.sub(
            r'(\n[ \t]*)if\s+not\s+_passes_whitelist\(it\)\s*:\s*\n',
            r'\1if require_wl and (not _passes_whitelist(it)):\n',
            out_block,
            count=1
        )
        out_block = out_block2

    out = src[:i0] + out_block + src[i1:]
    bak = _backup(path, src)
    _write(path, out)
    print("OK: au_politics strict whitelist enabled (v3f).")
    print("Backup:", bak)

if __name__ == "__main__":
    main()
