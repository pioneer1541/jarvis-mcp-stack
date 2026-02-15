import os, re, shutil

APP="app.py"
BAK="app.py.bak.music_volume_fallback_v1"

def read(p):
    with open(p,"r",encoding="utf-8") as f:
        return f.read()

def write(p,s):
    with open(p,"w",encoding="utf-8") as f:
        f.write(s)

def find_block(src, start_pat, end_pat=None):
    m=re.search(start_pat, src, flags=re.M)
    if not m:
        return None
    s=m.start()
    if not end_pat:
        return (s, len(src))
    m2=re.search(end_pat, src[m.end():], flags=re.M)
    if not m2:
        return (s, len(src))
    e=m.end()+m2.start()
    return (s, e)

def main():
    if not os.path.exists(APP):
        raise SystemExit("ERROR: cannot find "+APP)
    src=read(APP)
    shutil.copyfile(APP, BAK)

    # 1) inject helper _music_try_volume_updown (only once)
    if "def _music_try_volume_updown(" not in src:
        ins_pat=r"def _music_parse_volume\s*\("
        blk=find_block(src, ins_pat)
        if not blk:
            raise SystemExit("ERROR: cannot find def _music_parse_volume")
        helper = r'''
def _music_try_volume_updown(ent: str, direction: str = "up", steps: int = 1):
    """
    Fallback volume control using media_player.volume_up / volume_down.
    Returns dict: {ok, status_code?, data?}
    """
    d = "up" if str(direction or "up").lower().startswith("u") else "down"
    n = int(steps or 1)
    if n < 1:
        n = 1
    if n > 10:
        n = 10
    svc = "volume_up" if d == "up" else "volume_down"
    last = {"ok": False, "error": "not_called"}
    for _ in range(n):
        last = ha_call_service("media_player", svc, service_data={"entity_id": ent}, timeout_sec=10)
        if not (isinstance(last, dict) and last.get("ok")):
            return last
    return last
'''.lstrip("\n")
        src = src[:blk[0]] + helper + "\n" + src[blk[0]:]

    # 2) patch the "volume set" handling inside structured_music handler:
    # Replace the existing block:
    #   vol = _music_parse_volume(user_text)
    #   if vol is not None:
    #       r = ha_call_service(... volume_set ...)
    #       if r.get('ok'): ...
    #       return ...失败
    # with a version that:
    #   - clamps
    #   - on failure: exposes status_code
    #   - tries up/down fallback for delta-ish phrases or approximate for absolute
    pat = r"\n\s*# volume set\s*\n\s*vol\s*=\s*_music_parse_volume\(user_text\)\s*\n\s*if\s+vol\s+is\s+not\s+None:\s*\n(?:.|\n)*?\n\s*# next/previous"
    m = re.search(pat, src)
    if not m:
        raise SystemExit("ERROR: cannot locate volume set block in structured_music")

    repl = r'''
        # volume set (absolute, e.g. 音量50% / 音量 30)
        vol = _music_parse_volume(user_text)
        if vol is not None:
            try:
                vol = float(vol)
            except Exception:
                vol = None
            if vol is None:
                return {"ok": True, "route_type": "structured_music", "final": "设置音量失败。"}
            if vol < 0.0:
                vol = 0.0
            if vol > 1.0:
                vol = 1.0

            r = ha_call_service('media_player', 'volume_set', service_data={'entity_id': ent, 'volume_level': vol}, timeout_sec=10)
            if isinstance(r, dict) and r.get('ok'):
                pct = int(round(float(vol) * 100.0))
                return {"ok": True, "route_type": "structured_music", "final": "已设置音量为 {0}% 。".format(pct)}

            # fallback: approximate using volume_up/down (max 10 steps)
            cur = _music_get_volume_level(ent)
            if cur is None:
                cur = _music_unmute_default()
            try:
                cur = float(cur)
            except Exception:
                cur = _music_unmute_default()

            direction = "up" if float(vol) > float(cur) else "down"
            steps = int(round(abs(float(vol) - float(cur)) / 0.05))
            if steps < 1:
                steps = 1
            if steps > 10:
                steps = 10

            rr = _music_try_volume_updown(ent, direction=direction, steps=steps)
            if isinstance(rr, dict) and rr.get("ok"):
                if direction == "up":
                    return {"ok": True, "route_type": "structured_music", "final": "已调高音量。"}
                return {"ok": True, "route_type": "structured_music", "final": "已调低音量。"}

            sc = ""
            if isinstance(r, dict) and ("status_code" in r):
                sc = "（HTTP {0}）".format(r.get("status_code"))
            return {"ok": True, "route_type": "structured_music", "final": "设置音量失败{0}。".format(sc)}

        # volume delta (relative): 大一点/小一点/调大/调小
        dvol = _music_parse_volume_delta(user_text) if "def _music_parse_volume_delta" in globals() else None
        if dvol is not None:
            try:
                dvol = float(dvol)
            except Exception:
                dvol = None
            if dvol is None:
                return {"ok": True, "route_type": "structured_music", "final": "调整音量失败。"}

            # prefer precise volume_set if current volume known
            cur = _music_get_volume_level(ent)
            if cur is None:
                cur = _music_unmute_default()
            try:
                cur = float(cur)
            except Exception:
                cur = _music_unmute_default()

            nv = cur + dvol
            if nv < 0.0:
                nv = 0.0
            if nv > 1.0:
                nv = 1.0

            r = ha_call_service('media_player', 'volume_set', service_data={'entity_id': ent, 'volume_level': nv}, timeout_sec=10)
            if isinstance(r, dict) and r.get('ok'):
                return {"ok": True, "route_type": "structured_music", "final": "已调整音量。"}

            # fallback: volume_up/down once
            rr = _music_try_volume_updown(ent, direction=("up" if dvol > 0 else "down"), steps=1)
            if isinstance(rr, dict) and rr.get("ok"):
                if dvol > 0:
                    return {"ok": True, "route_type": "structured_music", "final": "已调高音量。"}
                return {"ok": True, "route_type": "structured_music", "final": "已调低音量。"}

            sc = ""
            if isinstance(r, dict) and ("status_code" in r):
                sc = "（HTTP {0}）".format(r.get("status_code"))
            return {"ok": True, "route_type": "structured_music", "final": "调整音量失败{0}。".format(sc)}

        # next/previous
'''.replace("\r\n","\n")

    src = src[:m.start()] + "\n" + repl + src[m.end()-len("\n        # next/previous\n"):]

    write(APP, src)
    print("OK: patched", APP)
    print("Backup:", BAK)

if __name__=="__main__":
    main()
