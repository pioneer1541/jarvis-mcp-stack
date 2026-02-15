#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import json

APP = "app.py"

def _backup(path: str) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = path + ".bak.news_v2_5." + ts
    with open(path, "rb") as fsrc:
        data = fsrc.read()
    with open(bak, "wb") as fdst:
        fdst.write(data)
    return bak

def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def _write_text(path: str, s: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)

def _ensure_import_json(s: str) -> str:
    # 如果已经 import json 就不动
    if re.search(r"^\s*import\s+json\s*$", s, flags=re.M):
        return s
    # 尽量插在 import 区块里（找到第一段 import 之后）
    m = re.search(r"^(import\s+[^\n]+\n)+", s, flags=re.M)
    if m:
        block = m.group(0)
        if "import json" not in block:
            block2 = block + "import json\n"
            return s[:m.start()] + block2 + s[m.end():]
    # 找不到 import 区块就加在文件开头
    return "import json\n" + s

def _fix_decorator_def_same_line(s: str) -> (str, int):
    """
    修复形如:
    @mcp.tool(... )def foo(...):
    变为:
    @mcp.tool(...)
    def foo(...):
    """
    n = 0
    pattern = re.compile(r"(^\s*@mcp\.tool\([^\n]*\)\s*)def(\s+)", flags=re.M)
    while True:
        m = pattern.search(s)
        if not m:
            break
        repl = m.group(1).rstrip() + "\n" + "def" + m.group(2)
        s = s[:m.start()] + repl + s[m.end():]
        n += 1
        if n > 50:
            break
    return s, n

def _rename_duplicate_news_digest_tool(s: str) -> (str, int):
    """
    如果存在多个 @mcp.tool(name="news_digest"...)
    则把前面的改名为 news_digest_legacy_N，只保留最后一个叫 news_digest
    """
    # 收集所有 decorator 行的位置（只匹配单行 decorator）
    deco_pat = re.compile(r'^\s*@mcp\.tool\([^\n]*name\s*=\s*"news_digest"[^\n]*\)\s*$', flags=re.M)
    matches = list(deco_pat.finditer(s))
    if len(matches) <= 1:
        return s, 0

    # 前 len-1 个重命名
    changed = 0
    for i, m in enumerate(matches[:-1], start=1):
        line = m.group(0)
        line2 = re.sub(r'name\s*=\s*"news_digest"', 'name="news_digest_legacy_' + str(i) + '"', line)
        if line2 != line:
            s = s[:m.start()] + line2 + s[m.end():]
            changed += 1
    return s, changed

def _find_function_block(s: str, func_name: str):
    """
    返回 (start_idx, end_idx, indent, header_line, block_text)
    以最左侧 def func_name 开始，直到下一个同级 def/class 或 EOF。
    """
    # 兼容返回类型标注
    pat = re.compile(r'^([ \t]*)def\s+' + re.escape(func_name) + r'\s*\(.*?\)\s*(?:->\s*[^:]+)?\s*:\s*$',
                     flags=re.M)
    m = pat.search(s)
    if not m:
        return None

    indent = m.group(1)
    start = m.start()
    # 从 def 行之后开始找块结尾
    after = m.end()
    # 找下一个同级 def/class（同缩进）
    next_pat = re.compile(r'^(%s)(def|class)\s+' % re.escape(indent), flags=re.M)
    m2 = next_pat.search(s, pos=after)
    end = m2.start() if m2 else len(s)
    header_line = s[m.start():s.find("\n", m.start())]
    block = s[start:end]
    return (start, end, indent, header_line, block)

def _ensure_coerce_rules_helper(s: str) -> (str, bool):
    """
    插入 _news__coerce_rules(x) helper（如果不存在）
    放在 _news__build_query 之前（若找得到），否则放在文件末尾。
    """
    if "def _news__coerce_rules" in s:
        return s, False

    helper = """
def _news__coerce_rules(x):
    \"""
    允许 rules_zh / rules_en 为:
      - list[dict]（推荐）
      - list[str]（会转换为 dict）
      - dict（会包成单元素 list）
      - str（尝试 json.loads；失败则当作 domain 字符串）
      - None（转为空 list）
    返回: list[dict]
    \"""
    if x is None:
        return []
    if isinstance(x, list):
        out = []
        for it in x:
            if isinstance(it, dict):
                out.append(it)
            elif isinstance(it, str):
                dom = it.strip()
                if dom:
                    out.append({"domain": dom})
        return out
    if isinstance(x, dict):
        return [x]
    if isinstance(x, str):
        t = x.strip()
        if not t:
            return []
        if (t.startswith("[") and t.endswith("]")) or (t.startswith("{") and t.endswith("}")):
            try:
                j = json.loads(t)
                return _news__coerce_rules(j)
            except Exception:
                pass
        return [{"domain": t}]
    return []
""".lstrip("\n")

    # 尝试插在 _news__build_query 之前
    m = re.search(r'^\s*def\s+_news__build_query\b', s, flags=re.M)
    if m:
        return s[:m.start()] + helper + "\n\n" + s[m.start():], True
    return s + "\n\n" + helper + "\n", True

def _patch_build_query_rules_concat(s: str) -> (str, int):
    """
    修复 _news__build_query 内部对 rules_zh / rules_en 的拼接与遍历：
      - 先 coerce 成 list[dict]
      - 再 for r in rules_zh + rules_en
    只要发现 'for r in (rules_zh or []) + (rules_en or [])' 就替换。
    """
    blk = _find_function_block(s, "_news__build_query")
    if not blk:
        return s, 0
    start, end, indent, header_line, block = blk

    # 找到那一行并替换
    # 注意保留缩进
    pat = re.compile(r'^([ \t]*)for\s+r\s+in\s+\(rules_zh\s+or\s+\[\]\)\s*\+\s*\(rules_en\s+or\s+\[\]\)\s*:\s*$',
                     flags=re.M)
    m = pat.search(block)
    if not m:
        # 兼容别的写法： (rules_zh or []) + (rules_en or [])
        pat2 = re.compile(r'^([ \t]*)for\s+r\s+in\s+\(rules_zh\s+or\s+\[\]\)\s*\+\s*\(rules_en\s+or\s+\[\]\)\s*:\s*$',
                          flags=re.M)
        m = pat2.search(block)

    if not m:
        return s, 0

    inner_indent = m.group(1)

    inject = []
    inject.append(inner_indent + "rules_zh = _news__coerce_rules(rules_zh)")
    inject.append(inner_indent + "rules_en = _news__coerce_rules(rules_en)")
    inject.append(inner_indent + "for r in (rules_zh + rules_en):")
    inject_text = "\n".join(inject)

    block2 = block[:m.start()] + inject_text + block[m.end():]

    s2 = s[:start] + block2 + s[end:]
    return s2, 1

def _ensure_news_digest_accepts_kwargs(s: str) -> (str, int):
    """
    让 news_digest 能接受 prefer_lang/user_text/**kwargs，避免 route_request 传参炸。
    只做“最小安全修复”：如果 def news_digest(...) 行里没有 **kwargs，就加上。
    """
    # 找 def news_digest
    pat = re.compile(r'^([ \t]*)def\s+news_digest\s*\(([^)]*)\)\s*(?:->\s*[^:]+)?\s*:\s*$',
                     flags=re.M)
    m = pat.search(s)
    if not m:
        return s, 0

    indent = m.group(1)
    args = m.group(2)

    if "**kwargs" in args:
        return s, 0

    # 确保包含 prefer_lang/user_text（如果已存在就不重复）
    need = []
    if re.search(r'\bprefer_lang\b', args) is None:
        need.append('prefer_lang: str = "zh"')
    if re.search(r'\buser_text\b', args) is None:
        need.append('user_text: str = ""')
    need.append("**kwargs")

    args2 = args.strip()
    if args2:
        args2 = args2 + ", " + ", ".join(need)
    else:
        args2 = ", ".join(need)

    new_line = indent + "def news_digest(" + args2 + "):"
    s2 = s[:m.start()] + new_line + s[m.end():]
    return s2, 1

def main():
    if not os.path.exists(APP):
        raise SystemExit("ERROR: app.py not found in current dir")

    s = _read_text(APP)
    bak = _backup(APP)

    changed = []

    s = _ensure_import_json(s)

    s, n1 = _fix_decorator_def_same_line(s)
    if n1:
        changed.append("fix_decorator_def_same_line=" + str(n1))

    s, n2 = _rename_duplicate_news_digest_tool(s)
    if n2:
        changed.append("rename_duplicate_news_digest_tool=" + str(n2))

    s, added = _ensure_coerce_rules_helper(s)
    if added:
        changed.append("add__news__coerce_rules=1")

    s, n3 = _patch_build_query_rules_concat(s)
    if n3:
        changed.append("patch__news__build_query_rules_concat=" + str(n3))

    s, n4 = _ensure_news_digest_accepts_kwargs(s)
    if n4:
        changed.append("ensure_news_digest_accepts_kwargs=" + str(n4))

    if not changed:
        print("No change needed.")
        print("Backup:", bak)
        return

    _write_text(APP, s)
    print("Backup:", bak)
    print("Patched:", ", ".join(changed))

if __name__ == "__main__":
    main()
