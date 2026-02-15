import re
import shutil
from datetime import datetime

APP = "app.py"

def backup():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = "app.py.bak.news_p2_purify_v1_{0}".format(ts)
    shutil.copyfile(APP, bak)
    return bak

def read_text():
    with open(APP, "r", encoding="utf-8") as f:
        return f.read()

def write_text(s):
    with open(APP, "w", encoding="utf-8") as f:
        f.write(s)

def patch_filters_lists(src):
    changed = []

    # 1) Expand FILTERS['au_politics']['blacklist'] with sports / generic noise
    # We match the au_politics dict block inside FILTERS = { ... }
    pat_au = re.compile(r'(?s)("au_politics"\s*:\s*\{\s*"whitelist"\s*:\s*\[.*?\]\s*,\s*"blacklist"\s*:\s*\[)(.*?)(\]\s*\}\s*,)', re.DOTALL)
    m = pat_au.search(src)
    if m:
        inside = m.group(2)
        add = [
            "socceroos","afl","nrl","cricket","tennis","rugby","football",
            "match","goal","coach","player","scores","highlights",
            "premier league","nba","nfl",
            "体育","足球","篮球","网球","板球","比赛","进球","教练","球员","比分"
        ]
        # avoid duplicates by simple containment check
        for a in add:
            if ('"{0}"'.format(a) in inside) or ("'{0}'".format(a) in inside):
                continue
            inside = inside.rstrip() + ', "{0}"'.format(a)
        src = src[:m.start(2)] + inside + src[m.end(2):]
        changed.append("filters_au_politics_blacklist_expand")

    # 2) Expand FILTERS['mel_life']['blacklist'] with lawn/garden/ugliest
    pat_ml = re.compile(r'(?s)("mel_life"\s*:\s*\{\s*"whitelist"\s*:\s*\[.*?\]\s*,\s*"blacklist"\s*:\s*\[)(.*?)(\]\s*\}\s*,)', re.DOTALL)
    m2 = pat_ml.search(src)
    if m2:
        inside2 = m2.group(2)
        add2 = ["lawn","garden","ugliest","world's ugliest","草坪","花园","最丑","世界最丑"]
        for a in add2:
            if ('"{0}"'.format(a) in inside2) or ("'{0}'".format(a) in inside2):
                continue
            inside2 = inside2.rstrip() + ', "{0}"'.format(a)
        src = src[:m2.start(2)] + inside2 + src[m2.end(2):]
        changed.append("filters_mel_life_blacklist_expand")

    return src, changed

def patch_must_anchor(src):
    changed = []

    # MUST_ANCHOR dict exists inside news_digest (per your earlier grep).
    # We update au_politics + mel_life entries with Australia/Melbourne anchoring.
    pat = re.compile(r'(?s)\n(?P<ind>[ \t]+)MUST_ANCHOR\s*=\s*\{.*?\n(?P=ind)\}\n', re.DOTALL)
    m = pat.search(src)
    if not m:
        return src, changed

    ind = m.group("ind")
    block = m.group(0)

    # Build new anchor lists (Australia-specific + politics; Melbourne/Victoria)
    au_anchor = [
        "australia","australian","canberra","federal","commonwealth",
        "parliament","senate","house","minister","cabinet","opposition",
        "prime minister","pm","treasurer","budget","bill","legislation",
        "labor","liberal","coalition","greens","nationals",
        "albanese","dutton","ley","hastie",
        "nsw","vic","qld","wa","sa","tas","act","nt",
        "sydney","melbourne","brisbane","perth","adelaide","hobart","darwin",
        "australian election","by-election",
        "immigration","visa","citizenship",
        "澳大利亚","澳洲","堪培拉","联邦","议会","参议院","众议院",
        "部长","内阁","反对党","总理","财政","预算","法案","立法",
        "工党","自由党","联盟党","绿党","国家党",
        "阿尔巴尼斯","达顿","苏珊","哈斯蒂",
        "新州","维州","昆州","西澳","南澳","塔州","首都领地","北领地",
        "移民","签证","入籍","选举"
    ]

    mel_anchor = [
        "melbourne","victoria","vic","ptv","metro","tram","train","bus","cbd",
        "yarra","docklands","st kilda","geelong","ballarat","bendigo",
        "police","fire","ambulance","road","freeway","traffic","hospital",
        "墨尔本","维州","本地","民生","交通","电车","火车","公交","市中心",
        "警方","火警","救护","道路","高速","拥堵","医院","政府","市政"
    ]

    # Replace or insert keys in MUST_ANCHOR block
    def repl_key_list(b, key, new_list):
        # match: "key": [ ... ],
        pk = re.compile(r'(?s)("{0}"\s*:\s*)\[(.*?)\](\s*,)'.format(re.escape(key)))
        mm = pk.search(b)
        new_items = ", ".join(['"{0}"'.format(x) for x in new_list])
        if mm:
            b2 = b[:mm.start(2)] + new_items + b[mm.end(2):]
            return b2, True
        # if missing, insert near top after '{'
        ins = '\n{0}    "{1}": [{2}],'.format(ind, key, new_items)
        p0 = b.find("{")
        if p0 >= 0:
            p1 = b.find("\n", p0)
            if p1 >= 0:
                b2 = b[:p1+1] + ins + b[p1+1:]
                return b2, True
        return b, False

    block2, ok1 = repl_key_list(block, "au_politics", au_anchor)
    if ok1:
        changed.append("must_anchor_au_politics_update")

    block3, ok2 = repl_key_list(block2, "mel_life", mel_anchor)
    if ok2:
        changed.append("must_anchor_mel_life_update")

    src2 = src[:m.start()] + block3 + src[m.end():]
    return src2, changed

def patch_pass_anchor_strict(src):
    changed = []

    # Replace the inner function def _passes_anchor_topic inside news_digest (indent 4 spaces)
    # Safer: locate by "\n    def _passes_anchor_topic" and replace until next "\n    def "
    m0 = re.search(r'\n[ \t]{4}def\s+_passes_anchor_topic\s*\(.*?\)\s*:\s*\n', src)
    if not m0:
        return src, changed

    start = m0.start() + 1  # keep leading \n
    m1 = re.search(r'\n[ \t]{4}def\s+', src[m0.end():])
    if not m1:
        return src, changed
    end = m0.end() + m1.start()

    # Build replacement with exact 4-space indent; include nonlocal for dropped_anchor if exists.
    repl_lines = [
        "    def _passes_anchor_topic(it: dict) -> bool:",
        "        # P2: strict anchor only for au_politics / mel_life to reduce category pollution",
        "        nonlocal dropped_anchor",
        "        strict_cats = set([\"au_politics\", \"mel_life\"])",
        "        anchors = MUST_ANCHOR.get(key) or []",
        "        if not anchors:",
        "            return True",
        "        txt = \"{0} {1} {2}\".format(it.get(\"title\") or \"\", it.get(\"snippet\") or \"\", it.get(\"source\") or \"\")",
        "        hit = _kw_hit(txt, anchors)",
        "        if key in strict_cats:",
        "            if not hit:",
        "                dropped_anchor += 1",
        "                return False",
        "        return True",
        ""
    ]
    repl = "\n".join(repl_lines)

    src2 = src[:start] + repl + src[end:]
    changed.append("passes_anchor_topic_strict_for_au_mel")
    return src2, changed

def main():
    bak = backup()
    src = read_text()

    changes = []

    src, c1 = patch_filters_lists(src)
    changes += c1

    src, c2 = patch_must_anchor(src)
    changes += c2

    src, c3 = patch_pass_anchor_strict(src)
    changes += c3

    write_text(src)

    print("OK: patched P2 (au_politics + mel_life purification).")
    print("Backup:", bak)
    print("Changes:", changes)

if __name__ == "__main__":
    main()
