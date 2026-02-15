#!/usr/bin/env python3
# Patch: add relative volume step (cur +/- step) for "音量大一点/小一点"
# - Insert BEFORE the "# volume set" line inside MUSIC_CONTROL_V1 block.
# - Idempotent by marker "MUSIC_VOLUME_STEP_V1".

import io
import os
import sys

APP = "app.py"
MARK = "MUSIC_VOLUME_STEP_V1"

def main():
    if not os.path.exists(APP):
        print("ERR: app.py not found in current dir")
        sys.exit(2)

    with io.open(APP, "r", encoding="utf-8") as f:
        src = f.read()

    if MARK in src:
        print("OK: already patched (marker found).")
        return

    lines = src.splitlines(True)

    # Find the MUSIC_CONTROL_V1 block and then find the first "# volume set" within it.
    music_idx = -1
    volset_idx = -1

    for i, ln in enumerate(lines):
        if "MUSIC_CONTROL_V1" in ln:
            music_idx = i
            break

    if music_idx < 0:
        print("ERR: cannot find MUSIC_CONTROL_V1 anchor")
        sys.exit(3)

    for i in range(music_idx, min(len(lines), music_idx + 800)):
        if "# volume set" in lines[i]:
            volset_idx = i
            break

    if volset_idx < 0:
        print("ERR: cannot find '# volume set' after MUSIC_CONTROL_V1")
        sys.exit(4)

    # Determine indentation from the volset line (it is inside the music control if-block)
    indent = lines[volset_idx].split("#")[0]
    # The code around is inside: if _is_music_control_query(...): then several nested ifs.
    # Use same indent level as "# volume set" line.

    block = []
    block.append(indent + "# " + MARK + "\n")
    block.append(indent + "# relative volume (up/down) based on current volume_level\n")
    block.append(indent + "t00 = (user_text or '').strip().lower()\n")
    block.append(indent + "is_up = False\n")
    block.append(indent + "is_dn = False\n")
    block.append(indent + "for _k in ['大一点','大声','大声点','调大','提高音量','louder','volume up','turn up']:\n")
    block.append(indent + "    if _k in t00:\n")
    block.append(indent + "        is_up = True\n")
    block.append(indent + "        break\n")
    block.append(indent + "for _k in ['小一点','小声','小声点','调小','降低音量','quieter','volume down','turn down']:\n")
    block.append(indent + "    if _k in t00:\n")
    block.append(indent + "        is_dn = True\n")
    block.append(indent + "        break\n")
    block.append(indent + "if is_up or is_dn:\n")
    block.append(indent + "    cur = _music_get_volume_level(ent)\n")
    block.append(indent + "    if cur is None:\n")
    block.append(indent + "        cur = _music_unmute_default()\n")
    block.append(indent + "    # step configurable by env MUSIC_VOLUME_STEP (default 0.05)\n")
    block.append(indent + "    step_s = str(os.environ.get('MUSIC_VOLUME_STEP') or '0.05').strip()\n")
    block.append(indent + "    try:\n")
    block.append(indent + "        step = float(step_s)\n")
    block.append(indent + "    except Exception:\n")
    block.append(indent + "        step = 0.05\n")
    block.append(indent + "    if step <= 0.0:\n")
    block.append(indent + "        step = 0.05\n")
    block.append(indent + "    if step > 0.5:\n")
    block.append(indent + "        step = 0.5\n")
    block.append(indent + "    target = cur + (step if is_up else (-step))\n")
    block.append(indent + "    if target < 0.0:\n")
    block.append(indent + "        target = 0.0\n")
    block.append(indent + "    if target > 1.0:\n")
    block.append(indent + "        target = 1.0\n")
    block.append(indent + "    r = ha_call_service('media_player', 'volume_set', service_data={'entity_id': ent, 'volume_level': float(target)}, timeout_sec=10)\n")
    block.append(indent + "    if isinstance(r, dict) and r.get('ok'):\n")
    block.append(indent + "        pct = int(round(float(target) * 100.0))\n")
    block.append(indent + "        return {'ok': True, 'route_type': 'structured_music', 'final': '已设置音量为 {0}% 。'.format(pct)}\n")
    block.append(indent + "    return {'ok': True, 'route_type': 'structured_music', 'final': '调整音量失败。'}\n")
    block.append(indent + "\n")

    # Insert block right before "# volume set"
    out_lines = lines[:volset_idx] + block + lines[volset_idx:]
    out = "".join(out_lines)

    with io.open(APP, "w", encoding="utf-8") as f:
        f.write(out)

    print("OK: patched app.py (relative volume step added).")

if __name__ == "__main__":
    main()
