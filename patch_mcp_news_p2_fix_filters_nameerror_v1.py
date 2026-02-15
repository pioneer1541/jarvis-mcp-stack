#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import re
import sys
from datetime import datetime

MARK_BEGIN = "# --- NEWS_DIGEST_FILTERS_AUTOGEN_BEGIN ---"
MARK_END   = "# --- NEWS_DIGEST_FILTERS_AUTOGEN_END ---"


def read_text(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return f.read()


def write_text(p, s):
    with io.open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(s)


def backup_file(p):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak.news_p2_fix_filters_" + ts
    write_text(bak, read_text(p))
    return bak


def build_filters_block():
    # 重点：
    # 1) 提供 FILTERS 全局定义，修复 NameError
    # 2) au_politics：加“音乐/娱乐/体育”topicban，避免被补满逻辑塞回去
    # 3) mel_life：lawn/garden/yard/ugliest lawn 等保持 ban
    return "\n".join([
        MARK_BEGIN,
        "FILTERS = {",
        "    \"world\": {",
        "        \"whitelist\": [],",
        "        \"blacklist\": [\"ufc\", \"mma\", \"boxing odds\", \"celebrity gossip\", \"porn\", \"onlyfans\"],",
        "    },",
        "    \"cn_finance\": {",
        "        \"whitelist\": [",
        "            \"财经\", \"经济\", \"金融\", \"股\", \"a股\", \"港股\", \"美股\", \"债\", \"基金\", \"利率\", \"通胀\", \"人民币\", \"央行\", \"证监\",",
        "            \"bank\", \"stocks\", \"market\", \"bond\", \"yields\", \"cpi\", \"gdp\"",
        "        ],",
        "        \"blacklist\": [\"ufc\", \"mma\", \"赛后\", \"足球\", \"篮球\", \"综艺\", \"八卦\", \"明星\", \"电影\", \"电视剧\"],",
        "    },",
        "    \"au_politics\": {",
        "        \"whitelist\": [",
        "            \"parliament\", \"senate\", \"house\", \"election\", \"labor\", \"coalition\", \"liberal\", \"greens\",",
        "            \"albanese\", \"dutton\", \"budget\", \"treasury\", \"immigration\", \"visa\", \"minister\", \"cabinet\",",
        "            \"议会\", \"选举\", \"工党\", \"自由党\", \"绿党\", \"预算\", \"内阁\", \"移民\", \"签证\"",
        "        ],",
        "        \"blacklist\": [",
        "            \"ufc\", \"mma\", \"sport\", \"match preview\", \"odds\", \"celebrity\",",
        "            \"socceroos\", \"afl\", \"nrl\", \"cricket\", \"tennis\", \"rugby\", \"football\", \"match\", \"goal\", \"coach\", \"player\", \"scores\", \"highlights\",",
        "            \"triple j\", \"hottest 100\", \"hilltop\", \"billie eilish\", \"billie\", \"music\", \"album\", \"concert\", \"festival\", \"tour\",",
        "            \"体育\", \"足球\", \"篮球\", \"网球\", \"板球\", \"比赛\", \"进球\", \"教练\", \"球员\", \"比分\",",
        "            \"音乐\", \"专辑\", \"演唱会\", \"巡演\", \"音乐节\"",
        "        ],",
        "    },",
        "    \"mel_life\": {",
        "        \"whitelist\": [",
        "            \"melbourne\", \"victoria\", \"vic\", \"cbd\", \"ptv\", \"metro\", \"tram\", \"train\", \"bus\",",
        "            \"police\", \"fire\", \"ambulance\", \"road\", \"freeway\", \"yarra\", \"docklands\", \"st kilda\",",
        "            \"墨尔本\", \"维州\", \"本地\", \"民生\", \"交通\", \"电车\", \"火车\", \"警方\", \"火警\", \"道路\"",
        "        ],",
        "        \"blacklist\": [",
        "            \"ufc\", \"mma\", \"celebrity\", \"gossip\", \"crypto shill\",",
        "            \"lawn\", \"garden\", \"ugliest\", \"world's ugliest\", \"ugliest lawn\", \"yard\", \"groundskeeper\",",
        "            \"草坪\", \"花园\", \"最丑\", \"世界最丑\", \"最丑草坪\"",
        "        ],",
        "    },",
        "    \"tech_internet\": {",
        "        \"whitelist\": [",
        "            \"ai\", \"openai\", \"google\", \"microsoft\", \"meta\", \"apple\", \"amazon\", \"tiktok\", \"x.com\", \"twitter\",",
        "            \"github\", \"open source\", \"linux\", \"android\", \"ios\", \"cloud\", \"security\", \"privacy\", \"regulation\", \"chip\", \"semiconductor\",",
        "            \"人工智能\", \"开源\", \"网络安全\", \"隐私\", \"监管\", \"芯片\", \"半导体\"",
        "        ],",
        "        \"blacklist\": [\"ufc\", \"mma\", \"crime\", \"murder\", \"celebrity\", \"gossip\", \"lottery\", \"horoscope\"],",
        "    },",
        "    \"tech_gadgets\": {",
        "        \"whitelist\": [",
        "            \"review\", \"hands-on\", \"launch\", \"iphone\", \"ipad\", \"mac\", \"samsung\", \"pixel\", \"camera\", \"laptop\", \"headphones\",",
        "            \"oled\", \"cpu\", \"gpu\", \"benchmark\", \"评测\", \"上手\", \"新品\", \"发布\", \"开箱\", \"相机\", \"手机\", \"耳机\", \"笔记本\"",
        "        ],",
        "        \"blacklist\": [\"ufc\", \"mma\", \"crime\", \"celebrity\", \"gossip\"],",
        "    },",
        "    \"gaming\": {",
        "        \"whitelist\": [",
        "            \"game\", \"gaming\", \"steam\", \"playstation\", \"ps5\", \"xbox\", \"nintendo\", \"switch\", \"patch\", \"update\", \"dlc\", \"release\", \"trailer\", \"esports\",",
        "            \"游戏\", \"主机\", \"更新\", \"补丁\", \"发售\", \"预告\"",
        "        ],",
        "        \"blacklist\": [\"ufc\", \"mma\", \"boxing\", \"wwe\", \"football\", \"basketball\", \"cricket\", \"horse racing\"],",
        "    },",
        "}",
        MARK_END,
        ""
    ])


def insert_or_replace_filters(src):
    # 1) 如果已有标记块：替换
    if MARK_BEGIN in src and MARK_END in src:
        pre, rest = src.split(MARK_BEGIN, 1)
        _, post = rest.split(MARK_END, 1)
        return pre + build_filters_block() + post

    # 2) 否则：插到 def news_digest 之前（保证全局可见）
    m = re.search(r"(?m)^\s*def\s+news_digest\s*\(", src)
    if not m:
        raise RuntimeError("Cannot find def news_digest(...) in app.py")

    ins = build_filters_block()
    return src[:m.start()] + ins + src[m.start():]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "app.py"
    if not os.path.exists(path):
        raise RuntimeError("File not found: {0}".format(path))

    src = read_text(path)

    # 如果已经有全局 FILTERS = ... 也没关系：我们用标记块管理，避免散落/重复/作用域错乱
    bak = backup_file(path)
    new_src = insert_or_replace_filters(src)
    write_text(path, new_src)

    print("OK patched:", path)
    print("Backup:", bak)
    print("Note: inserted/replaced FILTERS block with markers.")


if __name__ == "__main__":
    main()
