#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import sys
import shutil
import re

PATCH_TAG = "MUSIC_CONTROL_V1"


def read_text(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, s):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(s)


def backup_file(path):
    bak = path + ".bak"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
        print("OK: backup created:", bak)
    else:
        print("OK: backup exists:", bak)


def already_patched(s):
    return (PATCH_TAG in s)


def insert_before_anchor(s, anchor, block):
    idx = s.find(anchor)
    if idx < 0:
        return None
    return s[:idx] + block + "\n\n" + s[idx:]


def ensure_helpers(s):
    # Insert helper functions near router section (right before _route_request_impl definition if possible)
    anchor = "def _route_request_impl("
    idx = s.find(anchor)
    if idx < 0:
        return None

    helpers = []
    helpers.append("\n# " + PATCH_TAG + "\n")
    helpers.append("def _looks_like_media_player_entity(t: str) -> bool:\n")
    helpers.append("    try:\n")
    helpers.append("        x = str(t or '').strip()\n")
    helpers.append("        return x.startswith('media_player.') and len(x) > len('media_player.')\n")
    helpers.append("    except Exception:\n")
    helpers.append("        return False\n\n")

    helpers.append("def _music_default_player() -> str:\n")
    helpers.append("    # Priority: explicit env -> fallback empty\n")
    helpers.append("    for k in ['HA_DEFAULT_MEDIA_PLAYER', 'HA_DEFAULT_MUSIC_PLAYER', 'MA_DEFAULT_PLAYER']:\n")
    helpers.append("        v = str(os.environ.get(k) or '').strip()\n")
    helpers.append("        if v:\n")
    helpers.append("            return v\n")
    helpers.append("    return ''\n\n")

    helpers.append("def _music_extract_target_entity(user_text: str) -> str:\n")
    helpers.append("    # If user includes an explicit media_player.xxx, use it\n")
    helpers.append("    t = str(user_text or '')\n")
    helpers.append("    m = re.search(r'(media_player\\.[a-zA-Z0-9_]+)', t)\n")
    helpers.append("    if m:\n")
    helpers.append("        return str(m.group(1) or '').strip()\n")
    helpers.append("    return _music_default_player()\n\n")

    helpers.append("def _is_music_control_query(user_text: str) -> bool:\n")
    helpers.append("    t = (user_text or '').strip().lower()\n")
    helpers.append("    if not t:\n")
    helpers.append("        return False\n")
    helpers.append("    # Chinese + English keywords\n")
    helpers.append("    keys = [\n")
    helpers.append("        '播放', '继续', '暂停', '停一下', '停止', '下一首', '下一曲', '上一首', '上一曲',\n")
    helpers.append("        '音量', '静音', '取消静音', 'mute', 'unmute', 'pause', 'resume', 'play', 'stop', 'next', 'previous'\n")
    helpers.append("    ]\n")
    helpers.append("    for k in keys:\n")
    helpers.append("        if k in t:\n")
    helpers.append("            return True\n")
    helpers.append("    # also treat explicit media_player entity + control verb as music command\n")
    helpers.append("    if 'media_player.' in t:\n")
    helpers.append("        return True\n")
    helpers.append("    return False\n\n")

    helpers.append("def _music_parse_volume(user_text: str):\n")
    helpers.append("    # Return None or a float 0.0-1.0\n")
    helpers.append("    t = str(user_text or '').strip().lower()\n")
    helpers.append("    if not t:\n")
    helpers.append("        return None\n")
    helpers.append("    # patterns: 音量30 / 音量 30% / volume 0.3\n")
    helpers.append("    m = re.search(r'(音量|volume)\\s*[:：]?\\s*(\\d+(?:\\.\\d+)?)\\s*(%?)', t)\n")
    helpers.append("    if m:\n")
    helpers.append("        num = m.group(2)\n")
    helpers.append("        pct = m.group(3)\n")
    helpers.append("        try:\n")
    helpers.append("            v = float(num)\n")
    helpers.append("        except Exception:\n")
    helpers.append("            v = None\n")
    helpers.append("        if v is None:\n")
    helpers.append("            return None\n")
    helpers.append("        if pct == '%':\n")
    helpers.append("            v = v / 100.0\n")
    helpers.append("        else:\n")
    helpers.append("            # if user gave 0-1, keep; if 1-100 assume percent\n")
    helpers.append("            if v > 1.0:\n")
    helpers.append("                v = v / 100.0\n")
    helpers.append("        if v < 0.0:\n")
    helpers.append("            v = 0.0\n")
    helpers.append("        if v > 1.0:\n")
    helpers.append("            v = 1.0\n")
    helpers.append("        return v\n")
    helpers.append("    # colloquial: 一半/最大/最小\n")
    helpers.append("    if '一半' in t or '50%' in t:\n")
    helpers.append("        return 0.5\n")
    helpers.append("    if '最大' in t or '100%' in t:\n")
    helpers.append("        return 1.0\n")
    helpers.append("    if '最小' in t or '0%' in t:\n")
    helpers.append("        return 0.0\n")
    helpers.append("    return None\n\n")

    helpers_block = "".join(helpers)
    # Insert helpers right before _route_request_impl definition
    out = s[:idx] + helpers_block + s[idx:]
    return out


def ensure_music_branch(s):
    # Insert branch before the news digest branch comment, which exists in current file
    anchor = "\n    # Semi-structured retrieval: news digest\n"
    if anchor not in s:
        # fallback anchor: the if _is_news_query(user_text):
        anchor = "\n    if _is_news_query(user_text):\n"
        if anchor not in s:
            return None

    branch = []
    branch.append("\n    # " + PATCH_TAG + "\n")
    branch.append("    # Structured / Live: music control via HA media_player services\n")
    branch.append("    if _is_music_control_query(user_text):\n")
    branch.append("        ent = _music_extract_target_entity(user_text)\n")
    branch.append("        if not ent:\n")
    branch.append("            return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"未配置默认播放器。请在容器环境变量中设置 HA_DEFAULT_MEDIA_PLAYER（例如 media_player.living_room）。\"}\n")
    branch.append("\n")
    branch.append("        t0 = (user_text or '').strip().lower()\n")
    branch.append("        # mute/unmute\n")
    branch.append("        if ('取消静音' in t0) or ('unmute' in t0):\n")
    branch.append("            r = ha_call_service('media_player', 'volume_mute', service_data={'entity_id': ent, 'is_volume_muted': False}, timeout_sec=10)\n")
    branch.append("            if r.get('ok'):\n")
    branch.append("                return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"已取消静音。\"}\n")
    branch.append("            return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"取消静音失败。\"}\n")
    branch.append("\n")
    branch.append("        if ('静音' in t0) or ('mute' in t0):\n")
    branch.append("            r = ha_call_service('media_player', 'volume_mute', service_data={'entity_id': ent, 'is_volume_muted': True}, timeout_sec=10)\n")
    branch.append("            if r.get('ok'):\n")
    branch.append("                return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"已静音。\"}\n")
    branch.append("            return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"静音失败。\"}\n")
    branch.append("\n")
    branch.append("        # volume set\n")
    branch.append("        vol = _music_parse_volume(user_text)\n")
    branch.append("        if vol is not None:\n")
    branch.append("            r = ha_call_service('media_player', 'volume_set', service_data={'entity_id': ent, 'volume_level': vol}, timeout_sec=10)\n")
    branch.append("            if r.get('ok'):\n")
    branch.append("                pct = int(round(float(vol) * 100.0))\n")
    branch.append("                return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"已设置音量为 {0}% 。\".format(pct)}\n")
    branch.append("            return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"设置音量失败。\"}\n")
    branch.append("\n")
    branch.append("        # next/previous\n")
    branch.append("        if ('下一首' in t0) or ('下一曲' in t0) or ('next' in t0):\n")
    branch.append("            r = ha_call_service('media_player', 'media_next_track', service_data={'entity_id': ent}, timeout_sec=10)\n")
    branch.append("            if r.get('ok'):\n")
    branch.append("                return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"已切到下一首。\"}\n")
    branch.append("            return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"切歌失败。\"}\n")
    branch.append("\n")
    branch.append("        if ('上一首' in t0) or ('上一曲' in t0) or ('previous' in t0) or ('prev' in t0):\n")
    branch.append("            r = ha_call_service('media_player', 'media_previous_track', service_data={'entity_id': ent}, timeout_sec=10)\n")
    branch.append("            if r.get('ok'):\n")
    branch.append("                return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"已切到上一首。\"}\n")
    branch.append("            return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"切歌失败。\"}\n")
    branch.append("\n")
    branch.append("        # pause/play/stop\n")
    branch.append("        if ('暂停' in t0) or ('pause' in t0) or ('停一下' in t0):\n")
    branch.append("            r = ha_call_service('media_player', 'media_pause', service_data={'entity_id': ent}, timeout_sec=10)\n")
    branch.append("            if r.get('ok'):\n")
    branch.append("                return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"已暂停。\"}\n")
    branch.append("            return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"暂停失败。\"}\n")
    branch.append("\n")
    branch.append("        if ('停止' in t0) or ('stop' in t0):\n")
    branch.append("            r = ha_call_service('media_player', 'media_stop', service_data={'entity_id': ent}, timeout_sec=10)\n")
    branch.append("            if r.get('ok'):\n")
    branch.append("                return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"已停止播放。\"}\n")
    branch.append("            return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"停止失败。\"}\n")
    branch.append("\n")
    branch.append("        # default: play/resume\n")
    branch.append("        if ('播放' in t0) or ('继续' in t0) or ('play' in t0) or ('resume' in t0) or True:\n")
    branch.append("            r = ha_call_service('media_player', 'media_play', service_data={'entity_id': ent}, timeout_sec=10)\n")
    branch.append("            if r.get('ok'):\n")
    branch.append("                return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"已开始播放。\"}\n")
    branch.append("            return {\"ok\": True, \"route_type\": \"structured_music\", \"final\": \"播放失败。\"}\n")

    block = "".join(branch)
    out = insert_before_anchor(s, anchor, block)
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "app.py"
    if not os.path.exists(path):
        print("ERROR: file not found:", path)
        sys.exit(2)

    s = read_text(path)
    if already_patched(s):
        print("OK: already patched:", PATCH_TAG)
        sys.exit(0)

    backup_file(path)

    s2 = ensure_helpers(s)
    if s2 is None:
        print("ERROR: could not locate insertion point for helpers (def _route_request_impl)")
        sys.exit(3)

    s3 = ensure_music_branch(s2)
    if s3 is None:
        print("ERROR: could not locate insertion point for music branch (news anchor not found)")
        sys.exit(4)

    write_text(path, s3)
    print("OK: patched", path)


if __name__ == "__main__":
    main()
