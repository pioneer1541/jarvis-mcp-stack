#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import re
import sys
from datetime import datetime

APP = "app.py"
TAG = "music_listen_aliases_v2"

NEEDLE_PARTS = [
    "'音量'", "'静音'", "'取消静音'", "'mute'", "'unmute'",
    "'pause'", "'resume'", "'play'", "'stop'", "'next'", "'previous'"
]

LISTEN_COND = " or (('听' in t0) and (('歌' in t0) or ('音乐' in t0) or ('歌曲' in t0) or ('一首' in t0) or ('首' in t0)))"

def read_lines(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return f.read().splitlines(True)

def write_lines(p, lines):
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write("".join(lines))

def backup(p):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak." + TAG + "." + ts
    with io.open(p, "r", encoding="utf-8") as f:
        src = f.read()
    with io.open(bak, "w", encoding="utf-8") as f:
        f.write(src)
    return bak

def find_music_keywords_line(lines):
    idx = -1
    for i, ln in enumerate(lines):
        hit = True
        for p in NEEDLE_PARTS:
            if p not in ln:
                hit = False
                break
        if hit:
            idx = i
            break
    return idx

def extract_list_var_name(line):
    # try:   music_kws = [ ... ]
    m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\[", line)
    if m:
        return m.group(1)
    return ""

def patch_music_intent_condition(lines):
    """
    目标：把“进入 structured_music 的 if any(...)”那一行，统一加上 LISTEN_COND
    不依赖固定文本：通过 keywords 列表变量名定位 any(... in <var>) 的 if 行。
    """
    idx_kw = find_music_keywords_line(lines)
    if idx_kw < 0:
        return (lines, False, "WARN: cannot find music keywords list line; skip intent patch.")

    var = extract_list_var_name(lines[idx_kw])
    if not var:
        # fallback: assume list is inline; still try to patch nearby if any(any(...))
        var = ""

    idx_if = -1
    # search forward a bit: the intent if-line should be nearby
    for j in range(idx_kw, min(idx_kw + 140, len(lines))):
        ln = lines[j]
        s = ln.lstrip()
        if not s.startswith("if "):
            continue
        if "any(" not in ln:
            continue
        if " in t0" not in ln:
            continue
        if not ln.rstrip().endswith(":"):
            continue
        if var:
            if var not in ln:
                continue
        idx_if = j
        break

    if idx_if < 0:
        return (lines, False, "WARN: cannot locate music intent if-line; skip intent patch.")

    ln = lines[idx_if]
    if "('听' in t0)" in ln and ("'歌'" in ln or "'音乐'" in ln or "'歌曲'" in ln):
        return (lines, True, "OK: music listen intent already enabled.")

    ln2 = ln.rstrip("\n")
    if not ln2.endswith(":"):
        return (lines, False, "WARN: unexpected if-line format; skip intent patch.")
    ln2 = ln2[:-1] + LISTEN_COND + ":\n"
    lines[idx_if] = ln2
    return (lines, True, "OK: enabled listen-based music intent.")

def patch_alias_override(lines):
    """
    目标：确保 structured_music 分支里，ent 会被 HA_MEDIA_PLAYER_ALIASES 覆盖。
    定位点：ent = ...HA_DEFAULT_MEDIA_PLAYER_ENTITY... 之后，插入 alias 解析与覆盖。
    """
    # already patched?
    for ln in lines:
        if "HA_MEDIA_PLAYER_ALIASES" in ln and "aliases_map" in ln and "MUSIC_ALIASES_V2" in ln:
            return (lines, True, "OK: aliases override already patched.")

    idx_ent = -1
    for i, ln in enumerate(lines):
        if "HA_DEFAULT_MEDIA_PLAYER_ENTITY" in ln and ("ent" in ln) and ("=" in ln):
            idx_ent = i
            break
    if idx_ent < 0:
        return (lines, False, "WARN: cannot find ent assignment line; skip aliases patch.")

    indent = lines[idx_ent][:len(lines[idx_ent]) - len(lines[idx_ent].lstrip())]
    block = []
    block.append(indent + "# MUSIC_ALIASES_V2: override target player by HA_MEDIA_PLAYER_ALIASES\n")
    block.append(indent + "aliases_env = (os.environ.get('HA_MEDIA_PLAYER_ALIASES') or '').strip()\n")
    block.append(indent + "if aliases_env:\n")
    block.append(indent + "    aliases_map = {}\n")
    block.append(indent + "    for _p in [x.strip() for x in aliases_env.split(',') if x.strip()]:\n")
    block.append(indent + "        if ':' not in _p:\n")
    block.append(indent + "            continue\n")
    block.append(indent + "        _k, _v = _p.split(':', 1)\n")
    block.append(indent + "        _k = (_k or '').strip()\n")
    block.append(indent + "        _v = (_v or '').strip()\n")
    block.append(indent + "        if _k and _v:\n")
    block.append(indent + "            aliases_map[_k] = _v\n")
    block.append(indent + "    _t = (t0 or '')\n")
    block.append(indent + "    _tl = _t.lower()\n")
    block.append(indent + "    for _k, _v in aliases_map.items():\n")
    block.append(indent + "        if (_k in _t) or (_k.lower() in _tl):\n")
    block.append(indent + "            ent = _v\n")
    block.append(indent + "            break\n")
    block.append(indent + "\n")

    insert_at = idx_ent + 1
    out = lines[:insert_at] + block + lines[insert_at:]
    return (out, True, "OK: enabled HA_MEDIA_PLAYER_ALIASES target override.")

def main():
    if not os.path.exists(APP):
        print("ERROR: app.py not found")
        sys.exit(2)

    bak = backup(APP)
    lines = read_lines(APP)

    lines, ok1, msg1 = patch_music_intent_condition(lines)
    lines, ok2, msg2 = patch_alias_override(lines)

    write_lines(APP, lines)

    print(msg1)
    print(msg2)
    print("OK: patched app.py")
    print("Backup:", bak)

if __name__ == "__main__":
    main()
