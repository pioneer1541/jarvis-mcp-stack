#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import sys

APP = "app.py"

def _read(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()

def _write(path, s):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(s)

def _find_def_block(src, def_name):
    # return (start_idx, end_idx) for a top-level def block
    key = "def " + def_name + "("
    i = src.find(key)
    if i < 0:
        return (-1, -1)

    # ensure it's at beginning of line
    line_start = src.rfind("\n", 0, i)
    if line_start < 0:
        line_start = 0
    else:
        line_start = line_start + 1

    # find next top-level def after this one
    j = src.find("\ndef ", i + 1)
    if j < 0:
        return (line_start, len(src))
    return (line_start, j + 1)

def _replace_block(src, def_name, new_block):
    a, b = _find_def_block(src, def_name)
    if a < 0 or b < 0:
        return (src, False)
    out = src[:a] + new_block.rstrip() + "\n\n" + src[b:]
    return (out, True)

def main():
    if not os.path.exists(APP):
        print("ERR: cannot find {0}".format(APP))
        sys.exit(2)

    src = _read(APP)
    changed = False

    new_music_load_aliases = r'''
def _music_load_aliases() -> dict:
    """
    Parse HA_MEDIA_PLAYER_ALIASES:
      卧室:media_player.master_bedroom_speaker,主卧:media_player.master_bedroom_speaker,客厅:media_player.living_room_speaker_2
    Return lowercased key -> entity_id
    """
    raw = str(os.environ.get("HA_MEDIA_PLAYER_ALIASES") or "").strip()
    m = {}
    if not raw:
        return m
    parts = raw.split(",")
    for p in parts:
        p = str(p or "").strip()
        if (not p) or (":" not in p):
            continue
        k, v = p.split(":", 1)
        k = str(k or "").strip().lower()
        v = str(v or "").strip()
        if k and v:
            m[k] = v
    return m
'''.lstrip("\n")

    new_music_extract_target_entity = r'''
def _music_extract_target_entity(user_text: str) -> str:
    # If user includes an explicit media_player.xxx, use it
    t = str(user_text or "")
    m = re.search(r"(media_player\.[a-zA-Z0-9_]+)", t)
    if m:
        return str(m.group(1) or "").strip()

    # Otherwise, match room aliases first (卧室/客厅/主卧...)
    aliases = _music_load_aliases()
    if aliases:
        tl = t.strip().lower()
        keys = sorted(list(aliases.keys()), key=lambda x: len(x), reverse=True)
        for k in keys:
            if k and (k in tl):
                v = aliases.get(k) or ""
                v = str(v).strip()
                if v:
                    return v

    # Fallback: env default player
    return _music_default_player()
'''.lstrip("\n")

    new_is_music_control_query = r'''
def _is_music_control_query(user_text: str) -> bool:
    t = (user_text or "").strip().lower()
    if not t:
        return False

    # Direct control keywords
    keys = [
        "播放", "继续", "暂停", "停一下", "停止", "下一首", "下一曲", "上一首", "上一曲",
        "音量", "静音", "取消静音",
        "mute", "unmute", "pause", "resume", "play", "stop", "next", "previous",
        # natural language play intents
        "我想听", "我想要听", "来一首", "放一首", "来点", "来首", "放首", "听歌", "听音乐"
    ]
    for k in keys:
        if k in t:
            return True

    # Heuristic: "想...听..." (covers 我想在卧室听XXX)
    try:
        if re.search(r"想.{0,10}听", t):
            return True
    except Exception:
        pass

    # Heuristic: contains 听 + (歌/音乐/曲/一首/播放/来/放)
    if "听" in t:
        for w in ["歌", "音乐", "歌曲", "曲", "一首", "一曲", "播放", "来", "放"]:
            if w in t:
                return True

    # explicit entity id
    if "media_player." in t:
        return True

    return False
'''.lstrip("\n")

    # 1) Ensure _music_load_aliases exists (insert before _music_extract_target_entity if not present)
    if "def _music_load_aliases(" not in src:
        # insert right before def _music_extract_target_entity(
        needle = "def _music_extract_target_entity("
        pos = src.find(needle)
        if pos > 0:
            src = src[:pos] + new_music_load_aliases + "\n" + src[pos:]
            changed = True
            print("OK: inserted _music_load_aliases()")
        else:
            print("WARN: cannot insert _music_load_aliases (no _music_extract_target_entity found)")

    # 2) Replace _music_extract_target_entity
    src2, ok = _replace_block(src, "_music_extract_target_entity", new_music_extract_target_entity)
    if ok:
        src = src2
        changed = True
        print("OK: patched _music_extract_target_entity()")
    else:
        print("WARN: cannot patch _music_extract_target_entity (def not found)")

    # 3) Replace _is_music_control_query
    src2, ok = _replace_block(src, "_is_music_control_query", new_is_music_control_query)
    if ok:
        src = src2
        changed = True
        print("OK: patched _is_music_control_query()")
    else:
        print("WARN: cannot patch _is_music_control_query (def not found)")

    if not changed:
        print("NOOP: nothing changed")
        return

    _write(APP, src)
    print("OK: wrote {0}".format(APP))

if __name__ == "__main__":
    main()
