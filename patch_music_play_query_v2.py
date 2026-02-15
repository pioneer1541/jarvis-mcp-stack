#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import sys
import shutil
import subprocess
from datetime import datetime

APP = "app.py"
TAG = "music_play_query_v2"

MARK_LINE_CONTAINS = "MA_PLAY_QUERY_V1"
NEEDLE_MEDIA_PLAY = "ha_call_service('media_player', 'media_play'"

def main():
    if not os.path.exists(APP):
        print("ERROR: app.py not found in current dir")
        sys.exit(2)

    with io.open(APP, "r", encoding="utf-8") as f:
        lines = f.read().splitlines(True)

    idx_mark = -1
    for i, ln in enumerate(lines):
        if MARK_LINE_CONTAINS in ln:
            idx_mark = i
            break
    if idx_mark < 0:
        print("ERROR: cannot find existing marker:", MARK_LINE_CONTAINS)
        print("Hint: you may be on a different patch version; grep for 'MUSIC_ASSISTANT' or 'play_media'.")
        sys.exit(3)

    idx_media_play = -1
    for j in range(idx_mark, len(lines)):
        if NEEDLE_MEDIA_PLAY in lines[j]:
            idx_media_play = j
            break
    if idx_media_play < 0:
        print("ERROR: cannot find media_play call after marker.")
        sys.exit(4)

    # indent = indent of marker line
    indent = lines[idx_mark][:len(lines[idx_mark]) - len(lines[idx_mark].lstrip())]

    new_block = []
    new_block.append(indent + "# MA_PLAY_QUERY_V1 (replaced by V2): prefer Music Assistant play_media for '播放XXX'\n")
    new_block.append(indent + "if ('播放' in t0) or (t0.strip().startswith('play')):\n")
    new_block.append(indent + "    q = t0\n")
    new_block.append(indent + "    for _kw in ['开始播放', '播放一下', '帮我放', '我想听', '我想要听', '来一首', '放一首', '来点', '播放', 'play', 'resume']:\n")
    new_block.append(indent + "        q = q.replace(_kw, ' ')\n")
    new_block.append(indent + "    q = q.strip().strip('，。,.!?！？\"“”\\'')\n")
    new_block.append(indent + "    if q:\n")
    new_block.append(indent + "        # parse '周杰伦的夜曲' => artist='周杰伦', name='夜曲'\n")
    new_block.append(indent + "        artist = ''\n")
    new_block.append(indent + "        name = q\n")
    new_block.append(indent + "        if '的' in q:\n")
    new_block.append(indent + "            _p = q.split('的', 1)\n")
    new_block.append(indent + "            artist = (_p[0] or '').strip()\n")
    new_block.append(indent + "            name = (_p[1] or '').strip() or q.strip()\n")
    new_block.append(indent + "\n")
    new_block.append(indent + "        # decide type: '某某的歌/歌曲' => artist radio; otherwise track\n")
    new_block.append(indent + "        media_type = 'track'\n")
    new_block.append(indent + "        svc = {\n")
    new_block.append(indent + "            'entity_id': ent,\n")
    new_block.append(indent + "            'media_id': name,\n")
    new_block.append(indent + "            'media_type': media_type,\n")
    new_block.append(indent + "            'enqueue': 'replace'\n")
    new_block.append(indent + "        }\n")
    new_block.append(indent + "        if artist:\n")
    new_block.append(indent + "            svc['artist'] = artist\n")
    new_block.append(indent + "\n")
    new_block.append(indent + "        if ('的歌' in (t0 or '')) or ('的歌曲' in (t0 or '')):\n")
    new_block.append(indent + "            svc['media_type'] = 'artist'\n")
    new_block.append(indent + "            svc['media_id'] = artist or name\n")
    new_block.append(indent + "            svc['radio_mode'] = True\n")
    new_block.append(indent + "\n")
    new_block.append(indent + "        rr = ha_call_service('music_assistant', 'play_media', service_data=svc, timeout_sec=25)\n")
    new_block.append(indent + "        if isinstance(rr, dict) and rr.get('ok'):\n")
    new_block.append(indent + "            return {'ok': True, 'route_type': 'structured_music', 'final': '已开始播放。'}\n")
    new_block.append(indent + "        # fallback continues to media_play below\n")
    new_block.append(indent + "\n")

    # backup
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = APP + ".bak." + TAG + "." + ts
    shutil.copy2(APP, bak)

    out = lines[:idx_mark] + new_block + lines[idx_media_play:]
    with io.open(APP, "w", encoding="utf-8", newline="") as f:
        f.write("".join(out))

    # compile check
    subprocess.check_call(["python3", "-m", "py_compile", APP])

    print("OK: patched app.py")
    print("Backup:", bak)

if __name__ == "__main__":
    main()
