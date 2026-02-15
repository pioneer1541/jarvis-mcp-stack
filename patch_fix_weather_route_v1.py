import re

p = "app.py"
s = open(p, "r", encoding="utf-8").read()
orig = s

# 1) route_request: 入口先做 unicode 清洗（去零宽/怪空格）
# 把：user_text = (text or "").strip()
# 换成：user_text = _ug_clean_unicode((text or "").strip())
s2 = s
pat_route = r'(?m)^(def\s+route_request\(\s*text:\s*str\s*\)\s*->\s*dict\s*:\s*\n)([ \t]*)user_text\s*=\s*\(text\s*or\s*""\)\.strip\(\)\s*\n'
m = re.search(pat_route, s2)
if m:
    indent = m.group(2)
    repl = m.group(1) + indent + 'user_text = _ug_clean_unicode((text or "").strip())\n'
    s2 = re.sub(pat_route, repl, s2, count=1)

# 2) _route_type: 扩展 weather 关键词匹配，避免“今天的天气”漏判
pat_rt = r'(?s)(?m)^def\s+_route_type\(\s*user_text:\s*str\s*\)\s*->\s*str\s*:\s*\n(.*?)(?=^\s*# Structured: direct entity state query)'
m2 = re.search(pat_rt, s2)
if not m2:
    raise RuntimeError("cannot find _route_type block")

block = m2.group(0)

# 找到原 weather if 行并替换（按 '# Structured: weather' 锚点）
pat_weather = r'(?m)^\s*# Structured: weather\s*\n\s*if\s*\(.*?\)\s*:\s*\n\s*return\s*"structured_weather"\s*\n'
m3 = re.search(pat_weather, block)
if not m3:
    raise RuntimeError("cannot find weather branch inside _route_type")

new_weather = (
    '    # Structured: weather\n'
    '    # Make it robust for Chinese phrasing variants like "今天的天气怎么样"\n'
    '    if ("weather" in t) or ("forecast" in t) or ("天气" in t) or ("天氣" in t) or ("预报" in t) or ("氣象" in t) or ("气温" in t) or ("溫度" in t) or ("温度" in t) or ("下雨" in t) or ("降雨" in t) or ("雨" in t and "量" in t) or ("风" in t and ("速" in t or "大" in t)):\n'
    '        return "structured_weather"\n'
)

block2 = re.sub(pat_weather, new_weather, block, count=1)

# 写回整体
s3 = s2[:m2.start()] + block2 + s2[m2.end():]

open(p, "w", encoding="utf-8").write(s3)
print("patched_ok=1")
