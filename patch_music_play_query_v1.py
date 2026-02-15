#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import sys
import shutil

TARGET = os.path.join(os.path.dirname(__file__), "app.py")
BAK_TAG = "bak.music_play_query_v1"

MARK = "MA_PLAY_QUERY_V1"
NEEDLE = "ha_call_service('media_player', 'media_play'"

def main():
    if not os.path.exists(TARGET):
        print("ERROR: app.py not found at: " + TARGET)
        sys.exit(2)

    with io.open(TARGET, "r", encoding="utf-8") as f:
        lines = f.read().splitlines(True)

    # idempotent
    for ln in lines:
        if MARK in ln:
            print("OK: already patched (" + MARK + "). Nothing to do.")
            return

    idx = -1
    for i, ln in enumerate(lines):
        if NEEDLE in ln:
            idx = i
            break

    if idx < 0:
        print("ERROR: could not find media_play call line to patch.")
        sys.exit(3)

    call_line = lines[idx]
    indent = call_line[:len(call_line) - len(call_line.lstrip())]

    snippet = []
    snippet.append(indent + "# " + MARK + ": if user said '播放XXX' and XXX is not empty, try MA play_media first\n")
    snippet.append(indent + "if ('播放' in t0) or (t0.strip().startswith('play')):\n")
    snippet.append(indent + "    q = t0\n")
    snippet.append(indent + "    for _kw in ['开始播放', '播放一下', '帮我放', '我想听', '来点', '播放', 'play', 'resume']:\n")
    snippet.append(indent + "        q = q.replace(_kw, ' ')\n")
    snippet.append(indent + "    q = q.strip().strip('，。,.!?！？\"“”\\'')\n")
    snippet.append(indent + "    if q:\n")
    snippet.append(indent + "        _artist = ''\n")
    snippet.append(indent + "        _name = q\n")
    snippet.append(indent + "        if '的' in q:\n")
    snippet.append(indent + "            _p = q.split('的', 1)\n")
    snippet.append(indent + "            _artist = (_p[0] or '').strip()\n")
    snippet.append(indent + "            _name = (_p[1] or '').strip() or _artist\n")
    snippet.append(indent + "        media_obj = {'name': _name}\n")
    snippet.append(indent + "        if _artist:\n")
    snippet.append(indent + "            media_obj['artist'] = _artist\n")
    snippet.append(indent + "        svc_data = {\n")
    snippet.append(indent + "            'entity_id': ent,\n")
    snippet.append(indent + "            'media_id': media_obj,\n")
    snippet.append(indent + "            'media_type': 'track',\n")
    snippet.append(indent + "            'enqueue': 'replace'\n")
    snippet.append(indent + "        }\n")
    snippet.append(indent + "        rr = ha_call_service('music_assistant', 'play_media', service_data=svc_data, timeout_sec=20)\n")
    snippet.append(indent + "        if rr.get('ok'):\n")
    snippet.append(indent + "            return {'ok': True, 'route_type': 'structured_music', 'final': '已开始播放。'}\n")
    snippet.append(indent + "        # fallback continues to media_play below\n\n")

    # backup
    bak = TARGET + "." + BAK_TAG
    shutil.copy2(TARGET, bak)

    # insert before media_play call
    new_lines = lines[:idx] + snippet + lines[idx:]

    with io.open(TARGET, "w", encoding="utf-8", newline="") as f:
        f.write("".join(new_lines))

    print("OK: patched app.py")
    print("Backup: " + bak)

if __name__ == "__main__":
    main()
