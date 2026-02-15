#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import re
import sys
from datetime import datetime

APP = "app.py"
TAG = "music_room_play_v4"

def read_text(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, s):
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)

def backup(p):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak." + TAG + "." + ts
    with io.open(p, "r", encoding="utf-8") as f:
        src = f.read()
    with io.open(bak, "w", encoding="utf-8") as f:
        f.write(src)
    return bak

def ensure_music_apply_aliases(src):
    if "def _music_apply_aliases(" in src:
        return (src, False)

    helper = (
        "\n"
        "def _music_apply_aliases(user_text: str, ent: str) -> str:\n"
        "    \"\"\"Apply HA_MEDIA_PLAYER_ALIASES to override target entity.\n"
        "    Format: 卧室:media_player.xxx,主卧:media_player.yyy,客厅:media_player.zzz\n"
        "    \"\"\"\n"
        "    t = (user_text or \"\").strip()\n"
        "    tl = t.lower()\n"
        "    aliases_env = (os.environ.get('HA_MEDIA_PLAYER_ALIASES') or '').strip()\n"
        "    if not aliases_env:\n"
        "        return ent\n"
        "    aliases_map = {}\n"
        "    for p in [x.strip() for x in aliases_env.split(',') if x.strip()]:\n"
        "        if ':' not in p:\n"
        "            continue\n"
        "        k, v = p.split(':', 1)\n"
        "        k = (k or '').strip()\n"
        "        v = (v or '').strip()\n"
        "        if k and v:\n"
        "            aliases_map[k] = v\n"
        "    for k, v in aliases_map.items():\n"
        "        if (k in t) or (k.lower() in tl):\n"
        "            return v\n"
        "    return ent\n"
    )
    return (src + "\n" + helper + "\n", True)

def patch_query_slice(src):
    """
    Fix: if last verb is '播放' -> offset 2 chars; if '听' -> offset 1.
    We patch the line that assigns q = ...[_i+1:] into a small block.
    """
    # Try to find an existing slice line "q = ...[_i+1:].strip()"
    pat = re.compile(r"^(\s*)q\s*=\s*\(t0\s*or\s*''\)\[_i\+1:\]\.strip\(\)\s*$", re.M)
    m = pat.search(src)
    if not m:
        # also handle "q = t0[_i+1:].strip()"
        pat2 = re.compile(r"^(\s*)q\s*=\s*t0\[_i\+1:\]\.strip\(\)\s*$", re.M)
        m = pat2.search(src)
        if not m:
            return (src, False, "WARN: could not find query slice line; skip slice fix.")
    indent = m.group(1)

    block = (
        indent + "# MUSIC_QUERY_SLICE_V4: correct offset for 播放(2 chars) vs 听(1 char)\n"
        + indent + "_off = 1\n"
        + indent + "try:\n"
        + indent + "    if (_i_play >= 0) and (_i == _i_play):\n"
        + indent + "        _off = 2\n"
        + indent + "except Exception:\n"
        + indent + "    pass\n"
        + indent + "q = (t0 or '')[_i+_off:].strip()\n"
    )

    src2 = src[:m.start()] + block + src[m.end():]
    return (src2, True, "OK: fixed query slice offset (播放=2, 听=1).")

def patch_ma_play_media_entity_id(src):
    """
    Ensure service_data includes entity_id: ent when calling music_assistant.play_media.
    Also re-apply aliases right before the call.
    """
    # Find first occurrence of music_assistant play_media call
    idx = src.find("ha_call_service('music_assistant', 'play_media'")
    if idx < 0:
        idx = src.find('ha_call_service("music_assistant", "play_media"')
    if idx < 0:
        return (src, False, "WARN: cannot find music_assistant.play_media call; skip entity_id injection.")

    # Get a window around it
    win_start = max(0, idx - 400)
    win_end = min(len(src), idx + 800)
    win = src[win_start:win_end]

    # Insert alias apply + ensure entity_id in service_data dict
    # 1) inject alias apply line just before the ha_call_service line
    lines = win.splitlines(True)
    call_i = -1
    for i, ln in enumerate(lines):
        if "ha_call_service" in ln and "music_assistant" in ln and "play_media" in ln:
            call_i = i
            break
    if call_i < 0:
        return (src, False, "WARN: cannot locate play_media line in window; skip.")

    indent = re.match(r"^(\s*)", lines[call_i]).group(1)
    if "MUSIC_ALIAS_APPLY_BEFORE_MA_V4" not in win:
        inject = []
        inject.append(indent + "# MUSIC_ALIAS_APPLY_BEFORE_MA_V4\n")
        inject.append(indent + "try:\n")
        inject.append(indent + "    ent = _music_apply_aliases(t0 if 't0' in locals() else (text or ''), ent)\n")
        inject.append(indent + "except Exception:\n")
        inject.append(indent + "    pass\n")
        lines = lines[:call_i] + inject + lines[call_i:]
        call_i = call_i + len(inject)

    # 2) ensure service_data includes entity_id: ent
    # Search forward a few lines for "service_data={"
    sd_i = -1
    for j in range(call_i, min(call_i + 12, len(lines))):
        if "service_data" in lines[j] and "{" in lines[j]:
            sd_i = j
            break
    if sd_i < 0:
        # handle inline dict in same line
        ln = lines[call_i]
        if "service_data={" in ln and "entity_id" not in ln:
            lines[call_i] = ln.replace("service_data={", "service_data={'entity_id': ent, ", 1)
        # else cannot patch
    else:
        ln = lines[sd_i]
        if ("service_data={" in ln or "service_data = {" in ln) and ("entity_id" not in ln):
            # normalize: insert entity_id right after first "{"
            k = ln.find("{")
            if k >= 0:
                lines[sd_i] = ln[:k+1] + "'entity_id': ent, " + ln[k+1:]

    new_win = "".join(lines)
    src2 = src[:win_start] + new_win + src[win_end:]
    return (src2, True, "OK: injected entity_id into music_assistant.play_media and applied aliases before call.")

def main():
    if not os.path.exists(APP):
        print("ERROR: app.py not found")
        sys.exit(2)

    bak = backup(APP)
    src = read_text(APP)

    changed = False
    src, c0 = ensure_music_apply_aliases(src)
    changed = changed or c0

    src, c1, msg1 = patch_query_slice(src)
    changed = changed or c1

    src, c2, msg2 = patch_ma_play_media_entity_id(src)
    changed = changed or c2

    write_text(APP, src)

    print(msg1)
    print(msg2)
    print("OK: patched app.py")
    print("Backup:", bak)

    if not changed:
        print("WARN: nothing changed; patch may not have matched your current code.")
        sys.exit(3)

if __name__ == "__main__":
    main()
