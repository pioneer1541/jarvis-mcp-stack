import io
import os
import re
import shutil

APP = "app.py"
BAK = "app.py.bak.music_volume_delta_v1"

def read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def find_def_block(src, def_name):
    # return (start_idx, end_idx) inclusive/exclusive for function block
    lines = src.splitlines(True)
    pat = re.compile(r"^\s*def\s+" + re.escape(def_name) + r"\s*\(", re.M)
    m = pat.search(src)
    if not m:
        return None
    start = src.rfind("\n", 0, m.start())
    start = 0 if start < 0 else start + 1

    # determine indentation of def line
    def_line = src[start: src.find("\n", start) if src.find("\n", start) >= 0 else len(src)]
    indent = re.match(r"^(\s*)def\s+", def_line)
    base_indent = indent.group(1) if indent else ""

    # scan forward until next top-level def with same indent (or EOF)
    pos = src.find("\n", start)
    if pos < 0:
        return (start, len(src))
    pos += 1

    next_pat = re.compile(r"^" + re.escape(base_indent) + r"def\s+\w+\s*\(", re.M)
    m2 = next_pat.search(src, pos)
    if not m2:
        return (start, len(src))
    return (start, m2.start())

def insert_before(src, marker, block):
    idx = src.find(marker)
    if idx < 0:
        return (src, False)
    return (src[:idx] + block + src[idx:], True)

def main():
    if not os.path.exists(APP):
        raise SystemExit("ERROR: cannot find " + APP)

    src = read_text(APP)
    shutil.copyfile(APP, BAK)

    # 1) Replace _music_parse_volume with enhanced version
    blk = find_def_block(src, "_music_parse_volume")
    if not blk:
        raise SystemExit("ERROR: cannot find def _music_parse_volume")

    new_music_parse = r'''
def _music_parse_volume(user_text: str):
    # Return None or a float 0.0-1.0 (absolute volume)
    t = str(user_text or '').strip().lower()
    if not t:
        return None

    # patterns: 音量30 / 音量 30% / volume 0.3
    m = re.search(r'(音量|volume)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(%?)', t)
    if m:
        num = m.group(2)
        pct = m.group(3)
        try:
            v = float(num)
        except Exception:
            v = None
        if v is None:
            return None
        if pct == '%':
            v = v / 100.0
        else:
            # if user gave 0-1, keep; if 1-100 assume percent
            if v > 1.0:
                v = v / 100.0
        if v < 0.0:
            v = 0.0
        if v > 1.0:
            v = 1.0
        return v

    # Support: "70%" when it is clearly about volume (has 音量/volume/vol or common volume verbs)
    if ('音量' in t) or ('volume' in t) or ('vol' in t) or ('调大' in t) or ('调小' in t) or ('大一点' in t) or ('小一点' in t):
        m2 = re.search(r'(\d{1,3})\s*%', t)
        if m2:
            try:
                v = float(m2.group(1)) / 100.0
            except Exception:
                v = None
            if v is None:
                return None
            if v < 0.0:
                v = 0.0
            if v > 1.0:
                v = 1.0
            return v

    # colloquial: 一半/最大/最小
    if '一半' in t:
        return 0.5
    if '最大' in t:
        return 1.0
    if '最小' in t:
        return 0.0
    return None
'''.lstrip("\n")

    src = src[:blk[0]] + new_music_parse + src[blk[1]:]

    # 2) Insert _music_parse_volume_delta right after _music_parse_volume
    # (place it immediately after the function we just inserted)
    delta_fn = r'''

def _music_volume_step_default() -> float:
    v = str(os.environ.get('MUSIC_VOLUME_STEP') or '0.1').strip()
    try:
        f = float(v)
    except Exception:
        f = 0.1
    if f <= 0.0:
        f = 0.1
    if f > 1.0:
        f = 1.0
    return f

def _music_parse_volume_delta(user_text: str):
    """
    Return None or delta float (-1.0..+1.0) for relative volume intents:
      - 音量大一点/小一点/调大/调小/提高/降低
      - 加10%/减10%
      - turn up/down, louder/quieter
    """
    t = str(user_text or '').strip().lower()
    if not t:
        return None

    # explicit percent delta: 加10% / 减10%
    m = re.search(r'(加|提高|增大|增|大)\s*(\d{1,3})\s*%', t)
    if m:
        try:
            dv = float(m.group(2)) / 100.0
        except Exception:
            dv = None
        if dv is None:
            return None
        return abs(dv)

    m = re.search(r'(减|降低|减小|小)\s*(\d{1,3})\s*%', t)
    if m:
        try:
            dv = float(m.group(2)) / 100.0
        except Exception:
            dv = None
        if dv is None:
            return None
        return -abs(dv)

    up_keys = ['大一点', '大点', '调大', '提高音量', '声音大一点', ' louder', 'turn up', 'volume up', 'up ']
    down_keys = ['小一点', '小点', '调小', '降低音量', '声音小一点', ' quieter', 'turn down', 'volume down', 'down ']

    step = _music_volume_step_default()

    for k in up_keys:
        if k.strip() and (k.strip() in t):
            return step
    for k in down_keys:
        if k.strip() and (k.strip() in t):
            return -step

    # Chinese verbs without "一点"
    if ('调大' in t) or ('提高' in t) or ('增大' in t):
        return step
    if ('调小' in t) or ('降低' in t) or ('减小' in t):
        return -step

    return None
'''.lstrip("\n")

    # insert after the inserted _music_parse_volume function (find it by name and end)
    blk2 = find_def_block(src, "_music_parse_volume")
    if not blk2:
        raise SystemExit("ERROR: cannot locate _music_parse_volume after replacement")
    src = src[:blk2[1]] + delta_fn + src[blk2[1]:]

    # 3) In MUSIC_CONTROL_V1, add delta handling before "# next/previous"
    marker = "\n        # next/previous\n"
    delta_block = r'''
        # volume delta (大一点/小一点/调大/调小/加10%/减10%)
        dvol = _music_parse_volume_delta(user_text)
        if dvol is not None:
            cur = _music_get_volume_level(ent)
            if cur is None:
                cur = _music_unmute_default()
            try:
                nv = float(cur) + float(dvol)
            except Exception:
                nv = None
            if nv is None:
                return {"ok": True, "route_type": "structured_music", "final": "调整音量失败。"}
            if nv < 0.0:
                nv = 0.0
            if nv > 1.0:
                nv = 1.0
            r = ha_call_service('media_player', 'volume_set', service_data={'entity_id': ent, 'volume_level': nv}, timeout_sec=10)
            if isinstance(r, dict) and r.get('ok'):
                pct = int(round(float(nv) * 100.0))
                return {"ok": True, "route_type": "structured_music", "final": "已将音量调到 {0}% 。".format(pct)}
            return {"ok": True, "route_type": "structured_music", "final": "调整音量失败。"}

'''.lstrip("\n")

    src2, ok = insert_before(src, marker, delta_block)
    if not ok:
        raise SystemExit("ERROR: cannot find music marker for insertion: " + marker.strip())
    src = src2

    write_text(APP, src)
    print("OK: patched", APP)
    print("Backup:", BAK)

if __name__ == "__main__":
    main()
