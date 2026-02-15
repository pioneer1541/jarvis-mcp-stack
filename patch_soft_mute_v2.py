#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import sys
import shutil
import re
import subprocess
from datetime import datetime

TAG = "SOFT_MUTE_V2"

def read_text(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, s):
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(s)

def backup(p):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak." + TAG.lower() + "." + ts
    shutil.copy2(p, bak)
    return bak

def insert_helpers(src):
    if TAG in src:
        return src, False

    # Try to insert near existing music helpers
    anchor = "def _music_parse_volume("
    idx = src.find(anchor)
    if idx < 0:
        # fallback: insert before _route_request_impl
        anchor2 = "def _route_request_impl("
        idx2 = src.find(anchor2)
        if idx2 < 0:
            return None, False
        idx = idx2

    helpers = []
    helpers.append("\n# " + TAG + "\n")
    helpers.append("_MUSIC_SOFT_MUTE_CACHE = {}  # entity_id -> last_volume_level(float 0..1)\n\n")

    helpers.append("def _music_unmute_default() -> float:\n")
    helpers.append("    v = str(os.environ.get('MUSIC_UNMUTE_DEFAULT') or '0.3').strip()\n")
    helpers.append("    try:\n")
    helpers.append("        f = float(v)\n")
    helpers.append("    except Exception:\n")
    helpers.append("        f = 0.3\n")
    helpers.append("    if f < 0.0:\n")
    helpers.append("        f = 0.0\n")
    helpers.append("    if f > 1.0:\n")
    helpers.append("        f = 1.0\n")
    helpers.append("    return f\n\n")

    helpers.append("def _music_get_volume_level(ent: str):\n")
    helpers.append("    eid = str(ent or '').strip()\n")
    helpers.append("    if not eid:\n")
    helpers.append("        return None\n")
    helpers.append("    r = ha_get_state(eid, timeout_sec=10)\n")
    helpers.append("    if not isinstance(r, dict) or (not r.get('ok')):\n")
    helpers.append("        return None\n")
    helpers.append("    data = r.get('data') or {}\n")
    helpers.append("    attrs = data.get('attributes') or {}\n")
    helpers.append("    vl = attrs.get('volume_level')\n")
    helpers.append("    try:\n")
    helpers.append("        if vl is None:\n")
    helpers.append("            return None\n")
    helpers.append("        return float(vl)\n")
    helpers.append("    except Exception:\n")
    helpers.append("        return None\n\n")

    helpers.append("def _music_soft_mute(ent: str, do_unmute: bool = False) -> dict:\n")
    helpers.append("    eid = str(ent or '').strip()\n")
    helpers.append("    if not eid:\n")
    helpers.append("        return {'ok': False, 'error': 'empty_entity'}\n")
    helpers.append("    if not do_unmute:\n")
    helpers.append("        cur = _music_get_volume_level(eid)\n")
    helpers.append("        if cur is None:\n")
    helpers.append("            cur = _music_unmute_default()\n")
    helpers.append("        _MUSIC_SOFT_MUTE_CACHE[eid] = cur\n")
    helpers.append("        rr = ha_call_service('media_player', 'volume_set', service_data={'entity_id': eid, 'volume_level': 0.0}, timeout_sec=10)\n")
    helpers.append("        if isinstance(rr, dict) and rr.get('ok'):\n")
    helpers.append("            return {'ok': True}\n")
    helpers.append("        return {'ok': False, 'error': 'volume_set_0_failed'}\n")
    helpers.append("    # unmute\n")
    helpers.append("    restore = _MUSIC_SOFT_MUTE_CACHE.get(eid)\n")
    helpers.append("    if restore is None:\n")
    helpers.append("        restore = _music_unmute_default()\n")
    helpers.append("    rr = ha_call_service('media_player', 'volume_set', service_data={'entity_id': eid, 'volume_level': float(restore)}, timeout_sec=10)\n")
    helpers.append("    if isinstance(rr, dict) and rr.get('ok'):\n")
    helpers.append("        return {'ok': True}\n")
    helpers.append("    return {'ok': False, 'error': 'volume_restore_failed'}\n\n")

    block = "".join(helpers)
    out = src[:idx] + block + src[idx:]
    return out, True

def patch_mute_blocks(src):
    # Replace the exact mute/unmute blocks you showed (robust enough for your current file)
    # Unmute block
    pat_unmute = re.compile(
        r"\n([ \t]*)if\s*\(\s*'取消静音'\s*in\s*t0\s*\)\s*or\s*\(\s*'unmute'\s*in\s*t0\s*\)\s*:\n"
        r"\1[ \t]+r\s*=\s*ha_call_service\('media_player',\s*'volume_mute',\s*service_data=\{'entity_id':\s*ent,\s*'is_volume_muted':\s*False\},\s*timeout_sec=10\)\n"
        r"\1[ \t]+if\s+r\.get\('ok'\)\s*:\n"
        r"\1[ \t]+return\s+\{\"ok\":\s*True,\s*\"route_type\":\s*\"structured_music\",\s*\"final\":\s*\"已取消静音。\"\}\n"
        r"\1[ \t]+return\s+\{\"ok\":\s*True,\s*\"route_type\":\s*\"structured_music\",\s*\"final\":\s*\"取消静音失败。\"\}\n",
        re.DOTALL
    )

    def repl_unmute(m):
        ind = m.group(1)
        b = []
        b.append("\n" + ind + "if ('取消静音' in t0) or ('unmute' in t0):\n")
        b.append(ind + "    r = ha_call_service('media_player', 'volume_mute', service_data={'entity_id': ent, 'is_volume_muted': False}, timeout_sec=10)\n")
        b.append(ind + "    if isinstance(r, dict) and r.get('ok'):\n")
        b.append(ind + "        return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"已取消静音。\"}\n")
        b.append(ind + "    # fallback: soft unmute via volume_set\n")
        b.append(ind + "    rr = _music_soft_mute(ent, do_unmute=True)\n")
        b.append(ind + "    if isinstance(rr, dict) and rr.get('ok'):\n")
        b.append(ind + "        return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"已取消静音。\"}\n")
        b.append(ind + "    return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"当前播放器不支持静音。\"}\n")
        return "".join(b)

    # Mute block
    pat_mute = re.compile(
        r"\n([ \t]*)if\s*\(\s*'静音'\s*in\s*t0\s*\)\s*or\s*\(\s*'mute'\s*in\s*t0\s*\)\s*:\n"
        r"\1[ \t]+r\s*=\s*ha_call_service\('media_player',\s*'volume_mute',\s*service_data=\{'entity_id':\s*ent,\s*'is_volume_muted':\s*True\},\s*timeout_sec=10\)\n"
        r"\1[ \t]+if\s+r\.get\('ok'\)\s*:\n"
        r"\1[ \t]+return\s+\{\"ok\":\s*True,\s*\"route_type\":\s*\"structured_music\",\s*\"final\":\s*\"已静音。\"\}\n"
        r"\1[ \t]+return\s+\{\"ok\":\s*True,\s*\"route_type\":\s*\"structured_music\",\s*\"final\":\s*\"静音失败。\"\}\n",
        re.DOTALL
    )

    def repl_mute(m):
        ind = m.group(1)
        b = []
        b.append("\n" + ind + "if ('静音' in t0) or ('mute' in t0):\n")
        b.append(ind + "    r = ha_call_service('media_player', 'volume_mute', service_data={'entity_id': ent, 'is_volume_muted': True}, timeout_sec=10)\n")
        b.append(ind + "    if isinstance(r, dict) and r.get('ok'):\n")
        b.append(ind + "        return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"已静音。\"}\n")
        b.append(ind + "    # fallback: soft mute via volume_set (remember volume then set 0)\n")
        b.append(ind + "    rr = _music_soft_mute(ent, do_unmute=False)\n")
        b.append(ind + "    if isinstance(rr, dict) and rr.get('ok'):\n")
        b.append(ind + "        return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"已静音。\"}\n")
        b.append(ind + "    return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"当前播放器不支持静音。\"}\n")
        return "".join(b)

    out, n1 = pat_unmute.subn(repl_unmute, src, count=1)
    out2, n2 = pat_mute.subn(repl_mute, out, count=1)
    return out2, (n1 > 0 or n2 > 0), (n1, n2)

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "app.py"
    if not os.path.exists(path):
        print("ERROR: file not found:", path)
        sys.exit(2)

    src = read_text(path)
    bak = backup(path)
    print("OK: backup =>", bak)

    src2, ins = insert_helpers(src)
    if src2 is None:
        print("ERROR: could not insert helpers (anchor not found).")
        sys.exit(3)

    src3, changed, counts = patch_mute_blocks(src2)
    if not changed and not ins:
        print("WARN: no changes made (already patched?)")
    else:
        print("OK: patched mute blocks, counts=", counts, "helpers_inserted=", ins)

    write_text(path, src3)

    # syntax check
    try:
        subprocess.check_call(["python3", "-m", "py_compile", path])
        print("OK: py_compile passed")
    except subprocess.CalledProcessError:
        print("ERROR: py_compile failed; restored backup.")
        shutil.copy2(bak, path)
        raise

if __name__ == "__main__":
    main()
