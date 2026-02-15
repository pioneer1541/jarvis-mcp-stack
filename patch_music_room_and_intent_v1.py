import io
import os
import re
import sys

TARGET = "app.py"

def read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def find_top_def_block(src, name):
    """
    Find a top-level 'def name(...):' block.
    Return (start_idx, end_idx). end_idx is start of next top-level def/class or EOF.
    """
    m = re.search(r"^def\s+" + re.escape(name) + r"\b.*?:\s*$", src, flags=re.M)
    if not m:
        return None
    start = m.start()

    after = src[m.end():]
    m2 = re.search(r"^(def|class)\s+\w+", after, flags=re.M)
    if m2:
        end = m.end() + m2.start()
    else:
        end = len(src)
    return (start, end)

def replace_top_def(src, name, new_block):
    rng = find_top_def_block(src, name)
    if not rng:
        return (src, False)
    start, end = rng
    out = src[:start] + new_block.rstrip() + "\n\n" + src[end:]
    return (out, True)

def patch_music_default_player(src):
    # optional: add backward compatible env key (if your code has this function)
    new_block = (
        "def _music_default_player() -> str:\n"
        "    # Default player entity id (config via env). Keep backward compatible keys.\n"
        "    return (\n"
        "        os.environ.get(\"HA_DEFAULT_MEDIA_PLAYER_ENTITY\")\n"
        "        or os.environ.get(\"HA_DEFAULT_MEDIA_PLAYER\")\n"
        "        or \"media_player.living_room_speaker_2\"\n"
        "    )\n"
    )
    return replace_top_def(src, "_music_default_player", new_block)

def patch_music_extract_target_entity(src):
    new_block = (
        "def _music_extract_target_entity(user_text: str) -> str:\n"
        "    \"\"\"Pick target media_player entity.\n"
        "\n"
        "    Priority:\n"
        "    1) explicit entity_id in text (media_player.xxx)\n"
        "    2) room hint in text -> env-defined player\n"
        "    3) default player\n"
        "    \"\"\"\n"
        "    t = (user_text or \"\").strip()\n"
        "    tl = t.lower()\n"
        "\n"
        "    m = re.search(r\"(media_player\\.[a-zA-Z0-9_]+)\", t)\n"
        "    if m:\n"
        "        return m.group(1)\n"
        "\n"
        "    # room -> player mapping (bedroom)\n"
        "    if (\"卧室\" in t) or (\"主卧\" in t) or (\"bedroom\" in tl) or (\"master bedroom\" in tl):\n"
        "        for k in [\n"
        "            \"HA_MEDIA_PLAYER_BEDROOM\",\n"
        "            \"HA_DEFAULT_MEDIA_PLAYER_BEDROOM\",\n"
        "            \"HA_BEDROOM_MEDIA_PLAYER\",\n"
        "            \"HA_MEDIA_PLAYER_MASTER_BEDROOM\",\n"
        "            \"HA_DEFAULT_MEDIA_PLAYER_MASTER_BEDROOM\",\n"
        "            \"HA_MASTER_BEDROOM_MEDIA_PLAYER\",\n"
        "        ]:\n"
        "            v = (os.environ.get(k) or \"\").strip()\n"
        "            if v:\n"
        "                return v\n"
        "\n"
        "    # room -> player mapping (living room) optional\n"
        "    if (\"客厅\" in t) or (\"living room\" in tl) or (\"lounge\" in tl):\n"
        "        for k in [\n"
        "            \"HA_MEDIA_PLAYER_LIVING_ROOM\",\n"
        "            \"HA_DEFAULT_MEDIA_PLAYER_LIVING_ROOM\",\n"
        "            \"HA_LIVING_ROOM_MEDIA_PLAYER\",\n"
        "        ]:\n"
        "            v = (os.environ.get(k) or \"\").strip()\n"
        "            if v:\n"
        "                return v\n"
        "\n"
        "    return _music_default_player()\n"
    )
    return replace_top_def(src, "_music_extract_target_entity", new_block)

def patch_is_music_control_query(src):
    new_block = (
        "def _is_music_control_query(user_text: str) -> bool:\n"
        "    t = (user_text or \"\").strip().lower()\n"
        "    if not t:\n"
        "        return False\n"
        "\n"
        "    # explicit controls\n"
        "    keys = [\n"
        "        \"音量\", \"volume\", \"暂停\", \"pause\", \"继续\", \"resume\", \"播放\", \"play\",\n"
        "        \"停止\", \"stop\", \"下一首\", \"next\", \"上一首\", \"previous\",\n"
        "        \"静音\", \"取消静音\", \"mute\", \"unmute\",\n"
        "        \"来一首\", \"来首\", \"放一首\", \"放首\", \"来点\",\n"
        "    ]\n"
        "    for k in keys:\n"
        "        if k in t:\n"
        "            return True\n"
        "\n"
        "    # natural language play intent (handle: 我想在卧室听XXX的歌)\n"
        "    if (\"听\" in t) and ((\"歌\" in t) or (\"音乐\" in t) or (\"一首\" in t) or (\"首\" in t)):\n"
        "        return True\n"
        "\n"
        "    return False\n"
    )
    return replace_top_def(src, "_is_music_control_query", new_block)

def patch_play_query_condition(src):
    # Broaden the MA play trigger line inside your music handler:
    # from: ... ('我想听' in t0) ...
    # to:   ... ('想听' in t0) or (('听' in t0) and ('歌'/'音乐'/'一首'...))
    old = "if ('播放' in t0) or ('继续' in t0) or ('play' in t0) or ('我想听' in t0) or ('我想要听' in t0) or ('来一首' in t0) or ('来首' in t0) or ('放一首' in t0) or ('放首' in t0):"
    if old in src:
        new = "if ('播放' in t0) or ('继续' in t0) or ('play' in t0) or ('我想听' in t0) or ('我想要听' in t0) or ('想听' in t0) or ('来一首' in t0) or ('来首' in t0) or ('放一首' in t0) or ('放首' in t0) or (('听' in t0) and (('歌' in t0) or ('音乐' in t0) or ('一首' in t0) or ('首' in t0))):"
        return (src.replace(old, new), True)

    # fallback: regex replace when spacing differs
    pat = re.compile(r"^(\s*)if\s*\(\s*'播放'\s*in\s*t0\)\s*or.*\(\s*'放首'\s*in\s*t0\)\s*:\s*$", re.M)
    m = pat.search(src)
    if not m:
        return (src, False)
    indent = m.group(1)
    new_line = indent + "if ('播放' in t0) or ('继续' in t0) or ('play' in t0) or ('我想听' in t0) or ('我想要听' in t0) or ('想听' in t0) or ('来一首' in t0) or ('来首' in t0) or ('放一首' in t0) or ('放首' in t0) or (('听' in t0) and (('歌' in t0) or ('音乐' in t0) or ('一首' in t0) or ('首' in t0))):"
    out = src[:m.start()] + new_line + src[m.end():]
    return (out, True)

def main():
    if not os.path.exists(TARGET):
        print("ERROR: %s not found" % TARGET)
        sys.exit(2)

    src = read_text(TARGET)

    changed_any = False

    # These defs must exist in your running app.py (the one you grepped line 4214/4542 from).
    src, c1 = patch_is_music_control_query(src)
    src, c2 = patch_music_extract_target_entity(src)
    src, c3 = patch_music_default_player(src)  # optional
    src, c4 = patch_play_query_condition(src)

    changed_any = c1 or c2 or c3 or c4

    if not c1:
        print("WARN: _is_music_control_query not patched (function not found).")
    if not c2:
        print("WARN: _music_extract_target_entity not patched (function not found).")
    if not c3:
        print("INFO: _music_default_player not patched (function not found) - ok.")
    if not c4:
        print("WARN: play query condition not patched (no matching line found).")

    if not changed_any:
        print("ERROR: nothing patched. This usually means you're patching the wrong app.py.")
        sys.exit(3)

    write_text(TARGET, src)
    print("OK: patched %s" % TARGET)

if __name__ == "__main__":
    main()
