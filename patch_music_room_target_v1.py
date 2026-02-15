#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import sys
import shutil
from datetime import datetime

APP = "app.py"
TAG = "music_room_target_v1"
MARK = "MUSIC_ROOM_TARGET_V1"

NEEDLE_ENV = "HA_DEFAULT_MEDIA_PLAYER_ENTITY"
NEEDLE_STRUCTURED_MUSIC = "structured_music"

def read_lines(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return f.read().splitlines(True)

def write_lines(p, lines):
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write("".join(lines))

def backup(p):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak." + TAG + "." + ts
    shutil.copy2(p, bak)
    return bak

def main():
    if not os.path.exists(APP):
        print("ERROR: app.py not found")
        sys.exit(2)

    lines = read_lines(APP)

    for ln in lines:
        if MARK in ln:
            print("OK: already patched (" + MARK + ")")
            return

    idx_insert = -1
    indent = ""

    for i, ln in enumerate(lines):
        if NEEDLE_ENV in ln and ("ent" in ln or "media_player" in ln):
            idx_insert = i + 1
            indent = ln[:len(ln) - len(ln.lstrip())]
            break

    if idx_insert < 0:
        for i, ln in enumerate(lines):
            if "structured_music" in ln and ("def " in ln or "if " in ln):
                idx_insert = i + 1
                indent = ln[:len(ln) - len(ln.lstrip())]
                break

    if idx_insert < 0:
        print("ERROR: cannot find insertion point. Please grep HA_DEFAULT_MEDIA_PLAYER_ENTITY in app.py.")
        sys.exit(3)

    block = []
    block.append(indent + "# " + MARK + ": map room words to target media_player entity\n")
    block.append(indent + "def _parse_aliases_env(s):\n")
    block.append(indent + "    m = {}\n")
    block.append(indent + "    ss = (s or '').strip()\n")
    block.append(indent + "    if not ss:\n")
    block.append(indent + "        return m\n")
    block.append(indent + "    parts = [p.strip() for p in ss.split(',') if p.strip()]\n")
    block.append(indent + "    for p in parts:\n")
    block.append(indent + "        if ':' not in p:\n")
    block.append(indent + "            continue\n")
    block.append(indent + "        k, v = p.split(':', 1)\n")
    block.append(indent + "        k = (k or '').strip()\n")
    block.append(indent + "        v = (v or '').strip()\n")
    block.append(indent + "        if k and v:\n")
    block.append(indent + "            m[k] = v\n")
    block.append(indent + "    return m\n")
    block.append(indent + "\n")
    block.append(indent + "aliases_map = {\n")
    block.append(indent + "    '卧室': 'media_player.master_bedroom_speaker',\n")
    block.append(indent + "    '主卧': 'media_player.master_bedroom_speaker',\n")
    block.append(indent + "    'master bedroom': 'media_player.master_bedroom_speaker',\n")
    block.append(indent + "    'bedroom': 'media_player.master_bedroom_speaker',\n")
    block.append(indent + "}\n")
    block.append(indent + "aliases_env = os.environ.get('HA_MEDIA_PLAYER_ALIASES') or ''\n")
    block.append(indent + "aliases_user = _parse_aliases_env(aliases_env)\n")
    block.append(indent + "for _k in aliases_user:\n")
    block.append(indent + "    aliases_map[_k] = aliases_user[_k]\n")
    block.append(indent + "\n")
    block.append(indent + "t_lower = (t0 or '').lower()\n")
    block.append(indent + "for _k, _eid in aliases_map.items():\n")
    block.append(indent + "    kk = (_k or '')\n")
    block.append(indent + "    if not kk:\n")
    block.append(indent + "        continue\n")
    block.append(indent + "    if (kk in (t0 or '')) or (kk.lower() in t_lower):\n")
    block.append(indent + "        ent = _eid\n")
    block.append(indent + "        break\n")
    block.append(indent + "\n")

    bak = backup(APP)
    out = lines[:idx_insert] + block + lines[idx_insert:]
    write_lines(APP, out)

    print("OK: patched app.py")
    print("Backup:", bak)

if __name__ == "__main__":
    main()
