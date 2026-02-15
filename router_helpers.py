import re


def has_strong_lookup_intent(text: str) -> bool:
    t = str(text or "")
    tl = t.lower()
    keys = [
        "查", "搜索", "搜一下", "查一下", "多少钱", "价格", "费用", "收费", "收费标准", "营业时间", "开门", "关门",
        "地址", "电话", "官网", "评价", "附近", "怎么去", "怎么", "如何", "教程", "步骤",
        "推荐", "建议", "规划", "安排", "计划", "对比", "先做", "还是",
        "停车费", "停车场", "restaurant", "shop", "recommend", "suggest", "plan", "compare",
        "address", "phone", "opening", "hours", "price", "cost", "parking", "where",
    ]
    for k in keys:
        if (k in t) or (k in tl):
            return True
    return False


def is_obvious_smalltalk(text: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return False
    for k in ["我有点累", "无聊", "给我点建议", "周末去哪里放松一下", "能不能陪我聊两句", "心情不好"]:
        if k in t:
            return True
    if has_strong_lookup_intent(t):
        return False
    if len(t) > 20:
        return False
    tl = t.lower()
    zh = {
        "你好", "您好", "嗨", "哈喽", "早上好", "下午好", "晚上好", "晚安",
        "谢谢", "谢谢你", "多谢", "好的", "好", "收到", "行", "可以", "哈哈",
        "你在吗", "你忙吗", "我有点累", "无聊", "给我点建议", "我想聊聊", "陪我聊聊天",
        "周末去哪里放松一下",
    }
    en = {
        "hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "got it",
        "good night", "are you there", "are you busy",
    }
    if t in zh:
        return True
    if tl in en:
        return True
    if len(t) <= 6 and (("好" in t) or ("谢" in t) or ("ok" in tl) or ("haha" in tl)):
        return True
    return False


def smalltalk_reply(text: str, prefer_lang: str) -> str:
    t = str(text or "").strip()
    tl = t.lower()
    if ("喝水" in t) and (("提醒" in t) or ("计划" in t) or ("建议" in t)):
        return "可以先从轻量计划开始：每小时喝 150-200ml，上午和下午各 3 次，睡前少量补水。要不要我按你的作息给你排成整天时间表？"
    if ("谢谢" in t) or ("thanks" in tl) or ("thank" in tl):
        return "不客气。"
    if ("晚安" in t) or ("good night" in tl):
        return "晚安。"
    if ("早上好" in t) or ("下午好" in t) or ("晚上好" in t) or ("你好" in t) or ("hello" in tl) or (tl == "hi"):
        return "你好，我在。你可以直接说想查什么。"
    if ("你在吗" in t) or ("你忙吗" in t):
        return "我在。你可以直接说想查什么。"
    if ("我有点累" in t) or ("无聊" in t):
        return "辛苦了，先喝点水休息一下。我可以陪你聊会儿，或者帮你查点轻松的话题。"
    if ("给我点建议" in t) or ("周末去哪里放松一下" in t):
        return "可以先从轻松一点开始：散步、咖啡、看一场电影，或者去附近公园走走。你更想室内还是户外？"
    if ("收到" in t) or ("好的" in t) or (tl in ["ok", "okay", "got it"]):
        return "好的。"
    return "我在。你可以直接说想查什么。"


def is_life_advice_intent(text: str) -> bool:
    t = str(text or "")
    tl = t.lower()
    keys = [
        "规划", "安排", "计划", "建议", "先做", "怎么办", "怎么安排", "我该", "要不要",
        "家务", "晚饭", "做饭", "放松", "省电费", "to do", "plan", "suggest", "advice",
    ]
    for k in keys:
        if (k in t) or (k in tl):
            return True
    return False


def life_advice_fallback(text: str, prefer_lang: str) -> str:
    t = str(text or "")
    if ("家务" in t) or ("收拾" in t):
        return "给你一个省力顺序：先做 10 分钟快速归位，再处理最耗时的一项，最后做 5 分钟收尾。你要我按今晚可用时间给你排成 30 分钟版吗？"
    if ("晚饭" in t) or ("做饭" in t):
        return "今晚可以走省时方案：一道主菜+一道蔬菜+主食，先下锅最耗时的那道。要不要我按你家现有食材给你出 3 个 20 分钟菜单？"
    if ("周末" in t) and (("放松" in t) or ("去哪" in t)):
        return "可以这样安排：半天户外散步+一顿喜欢的餐+晚上轻松活动。你更偏向室内还是户外？我可以给你两套具体行程。"
    if ("省电费" in t):
        return "先做三件最有效的：空调温度上调 1-2 度、热水器错峰、待机设备集中断电。要不要我按你家设备给你列一份一周执行清单？"
    return "我先给你一个可执行小方案：明确目标、分成 2-3 步、先做最容易完成的一步。你告诉我时间和优先级，我帮你排成可直接执行的版本。"


def is_home_control_like_intent(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    sl = s.lower()
    ignore_words = [
        "天气", "预报", "新闻", "日程", "假期", "holiday",
        "营业时间", "地址", "电话", "停车费", "收费标准",
    ]
    for k in ignore_words:
        if (k in s) or (k in sl):
            return False
    verbs_cn = ["打开", "关闭", "开启", "关掉", "设为", "设置", "调到", "调成", "调高", "调低", "切换", "启动", "停止", "锁上", "解锁"]
    verbs_en = ["turn on", "turn off", "set ", "open ", "close ", "start ", "stop ", "unlock", "lock "]
    has_verb = False
    for k in verbs_cn:
        if k in s:
            has_verb = True
            break
    if not has_verb:
        for k in verbs_en:
            if k in sl:
                has_verb = True
                break
    if not has_verb:
        return False
    device_words = [
        "灯", "空调", "温度", "扫地机器人", "机器人", "车库门", "窗帘", "风扇", "电视", "音箱", "插座", "开关",
        "light", "climate", "thermostat", "vacuum", "cover", "fan", "switch", "garage door", "tv", "speaker",
    ]
    for k in device_words:
        if (k in s) or (k in sl):
            return True
    return False


def web_query_tokens(query: str) -> list:
    q = str(query or "").lower()
    out = []
    for w in re.findall(r"[a-z0-9]{2,}", q):
        if w not in out:
            out.append(w)
    for k in [
        "停车", "停车费", "营业", "地址", "电话", "商场", "餐厅", "店铺", "停车场", "墨尔本",
        "电费", "网费", "家务", "晚饭", "做饭", "食材", "机场", "药店", "价格", "费用",
        "cbd", "box hill", "doncaster",
    ]:
        if k in str(query or "") and k not in out:
            out.append(k)
    return out
