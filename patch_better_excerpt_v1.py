import re

P = "app.py"
s = open(P, "r", encoding="utf-8").read()

# 找到 _ug_open_url_fetch 函数块范围
m = re.search(r"(?m)^def\s+_ug_open_url_fetch\s*\(.*?\)\s*->\s*dict\s*:\s*$", s)
if not m:
    raise SystemExit("cannot find _ug_open_url_fetch definition")

start = m.start()
rest = s[start:]
m_end = re.search(r"(?m)^\s*(?:@mcp\.tool|def\s+\w+\s*\(|if\s+__name__\s*==)\b", rest[1:])
end = start + (m_end.start() + 1 if m_end else len(rest))

blk = s[start:end]

# 在函数内找到 html->text 的处理位置：一般会有 r.text / html / unescape / strip tags
# 这里用“插入一个更强的提取函数 + 替换 excerpt 生成逻辑”的方式，尽量不依赖你当前具体实现细节
if "_ug_extract_readable_text" not in s:
    helper = r'''

def _ug_extract_readable_text(html_text: str) -> str:
    # Lightweight extractor: title + meta description + main/article text
    try:
        import re as _re
        import html as _html

        t = html_text or ""
        # title
        title = ""
        m1 = _re.search(r"(?is)<title[^>]*>(.*?)</title>", t)
        if m1:
            title = _html.unescape(m1.group(1))
        # meta description
        desc = ""
        m2 = _re.search(r'(?is)<meta[^>]+name=["\\\']description["\\\'][^>]+content=["\\\'](.*?)["\\\']', t)
        if m2:
            desc = _html.unescape(m2.group(1))

        # prefer main/article
        body = ""
        m3 = _re.search(r"(?is)<main[^>]*>(.*?)</main>", t)
        if m3:
            body = m3.group(1)
        else:
            m4 = _re.search(r"(?is)<article[^>]*>(.*?)</article>", t)
            if m4:
                body = m4.group(1)
            else:
                body = t

        # drop script/style
        body = _re.sub(r"(?is)<(script|style)[^>]*>.*?</\\1>", " ", body)
        # strip tags
        body = _re.sub(r"(?is)<[^>]+>", " ", body)

        # combine pieces
        parts = []
        if title:
            parts.append(title)
        if desc and (desc not in title):
            parts.append(desc)
        parts.append(body)

        out = " \n".join([p for p in parts if p])
        out = _re.sub(r"[\\r\\t]+", " ", out)
        out = _re.sub(r"[ ]{2,}", " ", out)
        out = _re.sub(r"\\n[ ]+", "\\n", out)
        out = _re.sub(r"\\n{3,}", "\\n\\n", out)
        out = out.strip()
        return out
    except Exception:
        # fallback: raw
        return (html_text or "").strip()
'''
    # 插到文件顶部 import 区之后（找第一个空行后插入）
    m_top = re.search(r"(?m)^\s*$", s)
    if not m_top:
        raise SystemExit("cannot find insertion point for helper")
    s = s[:m_top.end()] + helper + s[m_top.end():]
    # 重新定位块
    m = re.search(r"(?m)^def\s+_ug_open_url_fetch\s*\(.*?\)\s*->\s*dict\s*:\s*$", s)
    start = m.start()
    rest = s[start:]
    m_end = re.search(r"(?m)^\s*(?:@mcp\.tool|def\s+\w+\s*\(|if\s+__name__\s*==)\b", rest[1:])
    end = start + (m_end.start() + 1 if m_end else len(rest))
    blk = s[start:end]

# 在 _ug_open_url_fetch 内，把 excerpt 的生成替换成调用 _ug_extract_readable_text
# 尝试把 "excerpt = ..." 那行替换；如果找不到，就在返回 ok True 之前插入 excerpt 赋值
if "excerpt =" in blk:
    blk2 = re.sub(r"(?m)^\s*excerpt\s*=.*$", "        excerpt = _ug_extract_readable_text(text)", blk, count=1)
else:
    # 在 ok True return 前插入
    blk2 = re.sub(
        r'(?ms)(return\s*\{\s*"ok"\s*:\s*True\s*,)',
        'excerpt = _ug_extract_readable_text(text)\n        \\1',
        blk,
        count=1
    )

# 确保返回里有 excerpt 字段（ok True 路径）
if '"excerpt"' not in blk2:
    blk2 = re.sub(
        r'(?ms)return\s*\{\s*"ok"\s*:\s*True\s*,\s*"url"\s*:\s*url\s*,',
        'return {"ok": True, "url": url, "excerpt": excerpt,',
        blk2,
        count=1
    )

s2 = s[:start] + blk2 + s[end:]
open(P, "w", encoding="utf-8").write(s2)
print("patched: better HTML excerpt extraction (title/description/main/article)")
