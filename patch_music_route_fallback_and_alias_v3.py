#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import re
import sys
from datetime import datetime

APP = "app.py"
TAG = "music_route_fallback_and_alias_v3"

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

def find_def_block(src, fn_name):
    m = re.search(r"^def\s+" + re.escape(fn_name) + r"\b.*?:\s*$", src, flags=re.MULTILINE)
    if not m:
        return None
    start = m.start()
    after = src[m.end():]
    m2 = re.search(r"^(def|class)\s+\w+", after, flags=re.MULTILINE)
    end = (m.end() + m2.start()) if m2 else len(src)
    return (start, end)

def ensure_helper(src):
    # Add helper only if not exists
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

    # insert after imports (best-effort): after first blank line following import section
    m = re.search(r"^(import\s+.+|from\s+.+\s+import\s+.+)(\r?\n)+", src, flags=re.MULTILINE)
    if m:
        pos = m.end()
        out = src[:pos] + helper + "\n" + src[pos:]
        return (out, True)

    return (src + "\n" + helper + "\n", True)

def patch_route_request_fallback(src):
    """
    In route_request(), at function start, add:
      if listen intent and not already has 播放:
         replace last '听' with '播放'
    """
    blk = find_def_block(src, "route_request")
    if not blk:
        return (src, False, "WARN: route_request not found; skip fallback.")

    start, end = blk
    body = src[start:end]

    if "MUSIC_LISTEN_FALLBACK_V3" in body:
        return (src, True, "OK: route_request fallback already present.")

    # find first line after docstring (or after signature line if no docstring)
    lines = body.splitlines(True)

    # locate insertion index: after docstring end if exists
    ins = None
    # find first non-empty line after def
    i = 0
    while i < len(lines) and not lines[i].lstrip().startswith("def "):
        i += 1
    i += 1  # after def line

    # skip possible docstring triple quotes
    if i < len(lines) and lines[i].lstrip().startswith('"""'):
        i += 1
        while i < len(lines):
            if '"""' in lines[i]:
                i += 1
                break
            i += 1

    # now i is good insertion point
    ins = i
    indent = re.match(r"^(\s*)", lines[ins] if ins < len(lines) else "    ").group(1)
    if indent == "":
        indent = "    "

    patch = []
    patch.append(indent + "# MUSIC_LISTEN_FALLBACK_V3: normalize '听…歌/音乐/一首' into 播放-intent to avoid open_domain\n")
    patch.append(indent + "t0 = (text or '').strip()\n")
    patch.append(indent + "if t0 and ('播放' not in t0) and ('play' not in t0.lower()):\n")
    patch.append(indent + "    _has_listen = ('听' in t0) and (('歌' in t0) or ('音乐' in t0) or ('歌曲' in t0) or ('一首' in t0) or ('首' in t0))\n")
    patch.append(indent + "    if _has_listen:\n")
    patch.append(indent + "        _i = t0.rfind('听')\n")
    patch.append(indent + "        if _i >= 0:\n")
    patch.append(indent + "            text = t0[:_i] + '播放' + t0[_i+1:]\n")

    lines = lines[:ins] + patch + lines[ins:]
    new_body = "".join(lines)
    out = src[:start] + new_body + src[end:]
    return (out, True, "OK: added route_request listen-fallback rewrite.")

def patch_music_alias_before_calls(src):
    """
    Find first occurrence of ha_call_service('media_player' ... entity_id': ent ...) within structured_music handler,
    and insert `ent = _music_apply_aliases(t0, ent)` just before that call (best effort).
    """
    # locate a region that likely is structured_music: search for route_type structured_music
    m = re.search(r"route_type['\"]\s*:\s*['\"]structured_music['\"]", src)
    if not m:
        # fallback: search for media_player volume_set calls
        m = re.search(r"ha_call_service\(\s*['\"]media_player['\"]", src)
        if not m:
            return (src, False, "WARN: cannot locate music handler region; skip aliases injection.")

    # find enclosing function by scanning upward to nearest top-level def
    up = src.rfind("\ndef ", 0, m.start())
    if up < 0:
        return (src, False, "WARN: cannot find enclosing def for music handler; skip aliases injection.")
    fn_start = up + 1
    # find function end
    after = src[fn_start:]
    m2 = re.search(r"^def\s+\w+", after[len("def "):], flags=re.MULTILINE)
    # careful: above search is not perfect; instead find next top-level def from fn_start+1
    m3 = re.search(r"^def\s+\w+", src[fn_start+1:], flags=re.MULTILINE)
    fn_end = (fn_start + 1 + m3.start()) if m3 else len(src)

    fn = src[fn_start:fn_end]
    if "MUSIC_ALIASES_APPLY_V3" in fn:
        return (src, True, "OK: aliases already applied in music handler.")

    # Find first ha_call_service('media_player', ...) line in this function
    lines = fn.splitlines(True)
    call_idx = -1
    for i, ln in enumerate(lines):
        if "ha_call_service" in ln and "media_player" in ln:
            call_idx = i
            break
    if call_idx < 0:
        return (src, False, "WARN: no ha_call_service(media_player) in handler; skip aliases injection.")

    indent = re.match(r"^(\s*)", lines[call_idx]).group(1)
    patch = []
    patch.append(indent + "# MUSIC_ALIASES_APPLY_V3: override target entity by HA_MEDIA_PLAYER_ALIASES\n")
    patch.append(indent + "try:\n")
    patch.append(indent + "    ent = _music_apply_aliases(t0 if 't0' in locals() else (text or ''), ent)\n")
    patch.append(indent + "except Exception:\n")
    patch.append(indent + "    pass\n")

    lines = lines[:call_idx] + patch + lines[call_idx:]
    new_fn = "".join(lines)
    out = src[:fn_start] + new_fn + src[fn_end:]
    return (out, True, "OK: injected alias override before media_player service call(s).")

def main():
    if not os.path.exists(APP):
        print("ERROR: app.py not found")
        sys.exit(2)

    bak = backup(APP)
    src = read_text(APP)

    changed = False

    src, c0 = ensure_helper(src)
    changed = changed or c0

    src, c1, msg1 = patch_route_request_fallback(src)
    changed = changed or c1

    src, c2, msg2 = patch_music_alias_before_calls(src)
    changed = changed or c2

    write_text(APP, src)

    print(msg1)
    print(msg2)
    print("OK: patched app.py")
    print("Backup:", bak)

    if not changed:
        print("WARN: nothing changed; you may be patching the wrong file.")
        sys.exit(3)

if __name__ == "__main__":
    main()
