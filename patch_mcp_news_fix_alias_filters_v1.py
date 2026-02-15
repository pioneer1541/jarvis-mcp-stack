import os
import time

APP = "app.py"

def main():
    if not os.path.exists(APP):
        raise SystemExit("missing app.py in current dir")

    src = open(APP, "r", encoding="utf-8").read().splitlines()

    # 1) 找到 news_digest 函数范围（用行级定位，避免脆弱 return 文本锚点）
    i0 = None
    for i, line in enumerate(src):
        if line.startswith("def news_digest("):
            i0 = i
            break
    if i0 is None:
        raise SystemExit("cannot find def news_digest(")

    # 2) 找到替换区间：从 key=... 到 import time as _time（不包含 import time 这一行）
    start = None
    end = None
    for i in range(i0, len(src)):
        if src[i].strip() == 'key = (category or "").strip()' and src[i].startswith("    "):
            start = i
            break
    if start is None:
        raise SystemExit("cannot find line: key = (category or \"\").strip() inside news_digest")

    for i in range(start + 1, len(src)):
        if src[i].strip() == "import time as _time" and src[i].startswith("    "):
            end = i
            break
    if end is None:
        raise SystemExit("cannot find line: import time as _time after key=...")

    # 3) 组装替换块（固定缩进 4 spaces）
    rep = []
    rep.append('    key = (category or "").strip()')
    rep.append('    category_input = key')
    rep.append("")
    rep.extend([
        '    aliases_map = {',
        '        "world": ["world（世界）", "世界新闻", "世界", "world", "World"],',
        '        "cn_finance": ["cn_finance（中国财经）", "中国财经", "财经", "cn finance", "china finance"],',
        '        "au_politics": ["au_politics（澳洲政治）", "澳洲政治", "澳大利亚政治", "Australia politics",',
        'australian politics", "AU politics", "Australian politics"],',
        '        "mel_life": ["mel_life（墨尔本民生）", "墨尔本民生", "维州民生", "Victoria"],',
        '        "tech_internet": ["tech_internet（互联网科技）", "互联网科技", "科技新闻", "Tech internet", "AI news"],',
        '        "tech_gadgets": ["tech_gadgets（数码新品评测）", "数码新品", "评测新闻", "Gadgets", "Tech reviews"],',
        '        "gaming": ["gaming（游戏）", "游戏新闻", "游戏", "Gaming"],',
        '    }',
        "",
        "    # --- NEWS_P2_REVERSE_ALIAS BEGIN ---",
        "    # Map display/category labels back to internal keys (e.g., 'Victoria' -> 'mel_life').",
        "    if key and (key not in aliases_map):",
        "        mapped = None",
        "        for ck, als in (aliases_map or {}).items():",
        "            for a0 in (als or []):",
        "                a = (str(a0) if a0 is not None else '').strip()",
        "                if not a:",
        "                    continue",
        "                if key == a:",
        "                    mapped = ck",
        "                    break",
        "            if mapped:",
        "                break",
        "        if mapped:",
        "            key = mapped",
        "    # --- NEWS_P2_REVERSE_ALIAS END ---",
        "",
        '    STRICT_WHITELIST_CATS = set(["au_politics"])',
        '    FILTERS = {',
        '        "world": {"whitelist": [], "blacklist": ["ufc", "mma", "boxing odds", "celebrity gossip", "porn", "onlyfans"]},',
        '        "cn_finance": {"whitelist": ["财经", "经济", "金融", "股", "a股", "港股", "美股", "债", "基金", "利率", "通胀", "人民币", "央行", "证监", "bank", "stocks", "market", "bond", "yields", "cpi", "gdp"],',
        '                      "blacklist": ["ufc", "mma", "赛后", "足球", "篮球", "综艺", "八卦", "明星", "电影", "电视剧"]},',
        '        "au_politics": {"whitelist": ["parliament", "senate", "house", "election", "labor", "coalition", "liberal", "greens", "albanese", "dutton", "budget", "treasury", "immigration", "visa", "minister", "cabinet", "议会", "选举", "工党", "自由党", "绿党", "预算", "内阁", "移民", "签证"],',
        '                        "blacklist": ["ufc", "mma", "sport", "match preview", "odds", "celebrity", "socceroos", "afl", "nrl", "cricket", "tennis", "rugby", "football", "match", "goal", "coach", "player", "scores", "highlights", "premier league", "nba", "nfl", "体育", "足球", "篮球", "网球", "板球", "比赛", "进球", "教练", "球员", "比分"]},',
        '        "mel_life": {"whitelist": ["melbourne", "victoria", "vic", "cbd", "ptv", "metro", "tram", "train", "bus", "police", "fire", "ambulance", "road", "freeway", "yarra", "docklands", "st kilda", "墨尔本", "维州", "本地", "民生", "交通", "电车", "火车", "警方", "火警", "道路"],',
        '                     "blacklist": ["ufc", "mma", "celebrity", "gossip", "crypto shill", "lawn", "garden", "ugliest", "world\'s ugliest", "草坪", "花园", "最丑", "世界最丑", "ugliest lawn", "yard", "groundskeeper", "最丑草坪"]},',
        '        "tech_internet": {"whitelist": ["ai", "openai", "google", "microsoft", "meta", "apple", "amazon", "tiktok", "x.com", "twitter", "github", "open source", "linux", "android", "ios", "cloud", "security", "privacy", "regulation", "chip", "semiconductor", "人工智能", "开源", "网络安全", "隐私", "监管", "芯片", "半导体"],',
        '                         "blacklist": ["ufc", "mma", "crime", "murder", "celebrity", "gossip", "lottery", "horoscope"]},',
        '        "tech_gadgets": {"whitelist": ["review", "hands-on", "launch", "iphone", "ipad", "mac", "samsung", "pixel", "camera", "laptop", "headphones", "oled", "cpu", "gpu", "benchmark", "评测", "上手", "新品", "发布", "开箱", "相机", "手机", "耳机", "笔记本"],',
        '                        "blacklist": ["ufc", "mma", "crime", "celebrity", "gossip"]},',
        '        "gaming": {"whitelist": ["game", "gaming", "steam", "playstation", "ps5", "xbox", "nintendo", "switch", "patch", "update", "dlc", "release", "trailer", "esports", "游戏", "主机", "更新", "补丁", "发售", "预告"],',
        '                   "blacklist": ["ufc", "mma", "boxing", "wwe", "football", "basketball", "cricket", "horse racing"]},',
        '    }',
        "",
        "    # --- NEWS_P3_CATEGORY_CANONICALIZE BEGIN ---",
        "    # If caller passed a fuzzy label, try to canonicalize to a known filter key.",
        "    if key and (key not in FILTERS):",
        "        for ck, als in (aliases_map or {}).items():",
        "            if ck == key:",
        "                break",
        "            for a0 in (als or []):",
        "                a = (str(a0) if a0 is not None else '').strip()",
        "                if not a:",
        "                    continue",
        "                if (a in key) or (key in a):",
        "                    key = ck",
        "                    break",
        "            if ck == key:",
        "                break",
        "    # --- NEWS_P3_CATEGORY_CANONICALIZE END ---",
        "",
    ])

    # 把原来的 _match_cat_id 函数体保留（不重写），从旧块里提取
    # 提取范围：原 start..end 中 "def _match_cat_id" 到 "cat_id = _match_cat_id"
    old = src[start:end]
    ms = None
    for i, line in enumerate(old):
        if line.startswith("    def _match_cat_id("):
            ms = i
            break
    if ms is None:
        raise SystemExit("cannot find def _match_cat_id inside replacement window")

    me = None
    for i in range(ms + 1, len(old)):
        if old[i].startswith("    cat_id = _match_cat_id("):
            me = i
            break
    if me is None:
        raise SystemExit("cannot find cat_id assignment inside replacement window")

    rep.extend(old[ms:me])

    rep.extend([
        "",
        "    cat_id = _match_cat_id(key)",
        "    if not cat_id:",
        "        # Fallback: try original input once.",
        "        cat_id2 = None",
        "        if category_input and (category_input != key):",
        "            cat_id2 = _match_cat_id(category_input)",
        "        if cat_id2:",
        "            cat_id = cat_id2",
        "        else:",
        "            return {",
        "                \"ok\": True,",
        "                \"category\": key,",
        "                \"category_input\": category_input,",
        "                \"stats\": None,",
        "                \"stats_detail\": None,",
        "                \"dropped_topicban\": None,",
        "                \"final\": \"Miniflux 中找不到对应分类：{0}\".format(category_input),",
        "                \"final_voice\": \"\",",
        "            }",
        "",
    ])

    # 4) 写回（先备份）
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = "app.py.bak.news_fix_alias_filters_v1_" + ts
    open(bak, "w", encoding="utf-8").write("\n".join(src) + "\n")

    out = src[:start] + rep + src[end:]
    open(APP, "w", encoding="utf-8").write("\n".join(out) + "\n")

    print("OK patched:", APP)
    print("Backup:", bak)
    print("Replaced lines:", start + 1, "to", end)

if __name__ == "__main__":
    main()
