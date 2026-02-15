#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import sys
import shutil
import subprocess
from datetime import datetime

APP = "app.py"
TAG = "music_intent_and_query_v4"

# marker(s) that should already exist in your file
MARK_PLAY_BLOCK = "# MA_PLAY_QUERY_V1 (replaced by V2): prefer Music Assistant play_media"

# we locate the music-intent keywords list line by these parts
NEEDLE_PARTS = [
    "'音量'", "'静音'", "'取消静音'", "'mute'", "'unmute'",
    "'pause'", "'resume'", "'play'", "'stop'", "'next'", "'previous'"
]

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

def patch_music_intent_condition(lines):
    """
    Find the music keywords list line, then patch the first following line that looks like:
      if any(k in t0 for k in XXX):
    to:
      if any(...) or (('听' in t0) and (('歌' in t0) or ('音乐' in t0) or ('歌曲' in t0))):
    """
    idx_kw = -1
    for i, ln in enumerate(lines):
        hit = True
        for p in NEEDLE_PARTS:
            if p not in ln:
                hit = False
                break
        if hit:
            idx_kw = i
            break

    if idx_kw < 0:
        return (lines, False, "WARN: cannot find music keywords list line; skip intent patch.")

    idx_if = -1
    for j in range(idx_kw, min(idx_kw + 80, len(lines))):
        ln = lines[j]
        s = ln.lstrip()
        if s.startswith("if ") and ("any(" in ln) and (" in t0" in ln) and ln.rstrip().endswith(":"):
            idx_if = j
            break

    if idx_if < 0:
        return (lines, False, "WARN: cannot find music intent if-line after keywords list; skip intent patch.")

    ln = lines[idx_if]
    if "('听' in t0)" in ln and "('歌' in t0)" in ln:
        return (lines, True, "OK: intent condition already patched.")

    # insert extra OR condition before colon
    ln2 = ln.rstrip("\n")
    if not ln2.endswith(":"):
        return (lines, False, "WARN: unexpected if-line format; skip intent patch.")

    add = " or (('听' in t0) and (('歌' in t0) or ('音乐' in t0) or ('歌曲' in t0)))"
    ln2 = ln2[:-1] + add + ":\n"
    lines[idx_if] = ln2
    return (lines, True, "OK: patched music intent condition.")

def patch_play_query_slice(lines):
    """
    In MA play_media block, replace:
      q = t0
    with:
      q = t0
      # slice after last '播放' or '听'
      _i_play = t0.rfind('播放')
      _i_listen = t0.rfind('听')
      _i = _i_play if _i_play > _i_listen else _i_listen
      if _i >= 0:
          q = t0[_i+1:].strip()
    """
    idx_mark = -1
    for i, ln in enumerate(lines):
        if MARK_PLAY_BLOCK in ln:
            idx_mark = i
            break
    if idx_mark < 0:
        return (lines, False, "WARN: cannot find MA play_media block marker; skip query slice patch.")

    idx_q = -1
    for j in range(idx_mark, min(idx_mark + 220, len(lines))):
        if lines[j].lstrip().startswith("q = t0"):
            idx_q = j
            break
    if idx_q < 0:
        return (lines, False, "WARN: cannot find 'q = t0' in MA block; skip query slice patch.")

    # Determine indent
    indent = lines[idx_q][:len(lines[idx_q]) - len(lines[idx_q].lstrip())]

    # If already patched, skip
    lookahead = "".join(lines[idx_q:idx_q+12])
    if "t0.rfind('播放')" in lookahead and "t0.rfind('听')" in lookahead:
        return (lines, True, "OK: query slice already patched.")

    new_chunk = []
    new_chunk.append(indent + "q = t0\n")
    new_chunk.append(indent + "# slice after the last play-verb so room words won't pollute query\n")
    new_chunk.append(indent + "_i_play = (t0 or '').rfind('播放')\n")
    new_chunk.append(indent + "_i_listen = (t0 or '').rfind('听')\n")
    new_chunk.append(indent + "_i = _i_play if _i_play > _i_listen else _i_listen\n")
    new_chunk.append(indent + "if _i >= 0:\n")
    new_chunk.append(indent + "    q = (t0 or '')[_i+1:].strip()\n")

    # Replace single line at idx_q with new chunk
    lines = lines[:idx_q] + new_chunk + lines[idx_q+1:]
    return (lines, True, "OK: patched query slicing in MA play_media block.")

def main():
    if not os.path.exists(APP):
        print("ERROR: app.py not found")
        sys.exit(2)

    lines = read_lines(APP)
    bak = backup(APP)

    lines, ok1, msg1 = patch_music_intent_condition(lines)
    lines, ok2, msg2 = patch_play_query_slice(lines)

    write_lines(APP, lines)
    try:
        subprocess.check_call(["python3", "-m", "py_compile", APP])
    except Exception as e:
        print("ERROR: py_compile failed. Restoring backup:", bak)
        shutil.copy2(bak, APP)
        raise

    print(msg1)
    print(msg2)
    print("OK: patched app.py")
    print("Backup:", bak)

if __name__ == "__main__":
    main()
