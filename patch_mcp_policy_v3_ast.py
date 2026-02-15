import ast
import os
import re
import time
import sys

APP_PATH = os.environ.get('MCP_APP') or './app.py'

def read_lines(p):
    with open(p, 'r', encoding='utf-8') as f:
        return f.read().splitlines(True)

def write_lines(p, lines):
    with open(p, 'w', encoding='utf-8') as f:
        f.writelines(lines)

def backup(p, lines):
    ts = time.strftime('%Y%m%d-%H%M%S')
    bak = p + '.bak.' + ts
    write_lines(bak, lines)
    return bak

def ensure_helper_blocks(text):
    changed = 0
    out = text

    if 'def _mcp__strip_snippet_meta' not in out:
        m = re.search(r"(def _mcp__clean_one_line\(t\):\n.*?\n\s*return x\n)", out, flags=re.S)
        if m:
            ins = (
                "\n\n"
                "def _mcp__strip_snippet_meta(t):\n"
                "    \"\"\"Remove common time/source prefixes like '3天前·新华社' from snippets.\"\"\"\n"
                "    x = _mcp__clean_one_line(t)\n"
                "    if not x:\n"
                "        return ''\n"
                "    x = re.sub(r'^\\s*\\d+\\s*(?:秒|分钟|小?时|天|周|月|年)前\\s*[·\\-–—|]\\s*', '', x)\n"
                "    x = re.sub(r'^\\s*\\d+\\s*(?:sec|secs|min|mins|hour|hours|day|days|week|weeks|month|months|year|years)\\s*ago\\s*[·\\-–—|]\\s*', '', x, flags=re.I)\n"
                "    x = re.sub(r'^\\s*[A-Za-z一-鿿]{2,12}\\s*[·\\-–—|]\\s*', '', x)\n"
                "    return x.strip()\n"
            )
            out = out[:m.end(1)] + ins + out[m.end(1):]
            changed += 1

    if 'def _mcp__relevance_low_heuristic' not in out:
        anchor = re.search(r"def _mcp__strip_snippet_meta\(t\):\n.*?\n\s*return x\.strip\(\)\n", out, flags=re.S)
        insert_pos = anchor.end(0) if anchor else 0
        ins2 = (
            "\n\n"
            "def _mcp__relevance_low_heuristic(query, best_title, best_snippet):\n"
            "    \"\"\"Minimal relevance check: if none of query keywords appear in title+snippet -> low.\"\"\"\n"
            "    q = (query or '').strip()\n"
            "    if not q:\n"
            "        return True\n"
            "    hay = ((best_title or '') + ' ' + (best_snippet or '')).lower()\n"
            "    zh = re.findall(r'[\\u4e00-\\u9fff]{2,6}', q)\n"
            "    en = re.findall(r'[A-Za-z]{3,}', q)\n"
            "    keys = []\n"
            "    for s in zh:\n"
            "        if s not in keys:\n"
            "            keys.append(s)\n"
            "    for s in en:\n"
            "        sl = s.lower()\n"
            "        if sl not in keys:\n"
            "            keys.append(sl)\n"
            "    keys = keys[:6]\n"
            "    if not keys:\n"
            "        return False\n"
            "    for k in keys:\n"
            "        if k.lower() in hay:\n"
            "            return False\n"
            "    return True\n"
        )
        out = out[:insert_pos] + ins2 + out[insert_pos:]
        changed += 1

    return out, changed

def remove_web_search_retry(text):
    out, n = re.subn(
        r"\n\s*# General-first fallback:.*?\n\s*except Exception:\n\s*pass\n",
        "\n",
        text,
        flags=re.S
    )
    return out, n

def find_func_span(lines, func_name):
    src = ''.join(lines)
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            if getattr(node, 'end_lineno', None) is None:
                raise SystemExit('ast end_lineno not available; need Python 3.8+')
            return node.lineno, node.end_lineno
    return None, None

def main():
    if not os.path.isfile(APP_PATH):
        raise SystemExit('APP_PATH not found: ' + APP_PATH)

    lines = read_lines(APP_PATH)
    full = ''.join(lines)
    if 'FastMCP("mcp-hello"' not in full and "FastMCP('mcp-hello'" not in full:
        raise SystemExit('This does not look like mcp-hello app.py: ' + APP_PATH)

    bak = backup(APP_PATH, lines)

    full2, n_retry = remove_web_search_retry(full)
    full3, n_help = ensure_helper_blocks(full2)

    lines3 = full3.splitlines(True)
    s, e = find_func_span(lines3, 'web_answer')
    if not s:
        raise SystemExit('web_answer not found')

    # NOTE: 为了避免 Zhihu 等页面 extract 乱码/变慢：只有 snippet 很短或明显截断时才 open
    new_func = (
        "def web_answer(\n"
        "    query: str,\n"
        "    max_sources: int = 3,\n"
        "    categories: str = 'general',\n"
        "    language: str = 'zh-CN',\n"
        "    time_range: str = '',\n"
        "    timeout_sec: int = 15,\n"
        "    max_chars_per_source: int = 400,\n"
        ") -> dict:\n"
        "    \"\"\"MCP_WEB_ANSWER_POLICY_V2 (Hard limits): 1 search + optional 1 open.\"\"\"\n"
        "    q = (query or '').strip()\n"
        "    if not q:\n"
        "        return {'ok': False, 'error': 'empty_query'}\n\n"
        "    pol = dict(MCP_WEB_ANSWER_POLICY or {})\n"
        "    _ = pol.get('prefer_domains') or []\n"
        "    _ = True if pol.get('allow_non_preferred') else False\n\n"
        "    try:\n"
        "        sr = web_search(q, k=3, categories=str(categories or 'general'), language=str(language or 'zh-CN'), time_range=str(time_range or ''))\n"
        "    except Exception as e:\n"
        "        return {'ok': False, 'error': 'web_search_failed', 'message': str(e)}\n\n"
        "    if (not isinstance(sr, dict)) or (not sr.get('ok')):\n"
        "        return {'ok': False, 'error': 'web_search_failed', 'detail': sr}\n\n"
        "    best_url = sr.get('best_url')\n"
        "    best_title = sr.get('best_title') or ''\n"
        "    best_snippet = sr.get('best_snippet') or sr.get('answer_hint') or ''\n"
        "    best_snippet = _mcp__strip_snippet_meta(best_snippet)\n"
        "    need_open = True if sr.get('need_open_url_extract') else False\n"
        "    relevance_low = sr.get('relevance_low')\n"
        "    if relevance_low is None:\n"
        "        try:\n"
        "            relevance_low = True if _mcp__relevance_low_heuristic(q, best_title, best_snippet) else False\n"
        "        except Exception:\n"
        "            relevance_low = False\n\n"
        "    # Only open when snippet is too short or clearly truncated\n"
        "    snippet_short = True if (len(best_snippet or '') < 120) else False\n"
        "    snippet_trunc = True if ((best_snippet or '').strip().endswith('...') or (best_snippet or '').strip().endswith('…')) else False\n"
        "    do_open = True if (need_open and best_url and (snippet_short or snippet_trunc)) else False\n\n"
        "    extract = None\n"
        "    extract_text = ''\n"
        "    if do_open:\n"
        "        try:\n"
        "            ex = open_url_extract(best_url, max_chars=int(max_chars_per_source), timeout_sec=float(timeout_sec))\n"
        "        except Exception as e:\n"
        "            ex = {'ok': False, 'error': 'open_url_extract_failed', 'message': str(e)}\n"
        "        extract = ex\n"
        "        if isinstance(ex, dict) and ex.get('ok'):\n"
        "            extract_text = _mcp__clean_one_line(ex.get('excerpt') or '')\n"
        "            extract_text = _mcp__strip_snippet_meta(extract_text)\n\n"
        "    answer = extract_text if extract_text else best_snippet\n"
        "    if (not answer) or (relevance_low is True):\n"
        "        kw1 = _mcp__clean_one_line(q) + ' 官方'\n"
        "        kw2 = _mcp__clean_one_line(q) + ' 时间 经过'\n"
        "        return {\n"
        "            'ok': True,\n"
        "            'query': sr.get('query') or q,\n"
        "            'answer': '我这次没找到足够可靠的信息来回答。',\n"
        "            'relevance_low': True,\n"
        "            'keyword_suggestions': [kw1, kw2],\n"
        "            'need_open_url_extract': need_open,\n"
        "            'best_url': best_url,\n"
        "            'detail': {'search': sr, 'extract': extract},\n"
        "        }\n\n"
        "    try:\n"
        "        answer = _mcp__first_sentence(answer, 240)\n"
        "    except Exception:\n"
        "        pass\n\n"
        "    return {\n"
        "        'ok': True,\n"
        "        'query': sr.get('query') or q,\n"
        "        'answer': answer,\n"
        "        'relevance_low': relevance_low,\n"
        "        'keyword_suggestions': None,\n"
        "        'need_open_url_extract': need_open,\n"
        "        'best_url': best_url,\n"
        "        'detail': {'search': sr, 'extract': extract},\n"
        "    }\n"
    )

    new_lines = lines3[:s-1] + [new_func] + lines3[e:]
    write_lines(APP_PATH, new_lines)

    sys.stdout.write('patched_path=' + APP_PATH + '\n')
    sys.stdout.write('backup_path=' + bak + '\n')
    sys.stdout.write('removed_search_retry_block=' + str(n_retry) + '\n')
    sys.stdout.write('helpers_added=' + str(n_help) + '\n')
    sys.stdout.write('web_answer_span=' + str(s) + '-' + str(e) + '\n')

if __name__ == '__main__':
    main()
