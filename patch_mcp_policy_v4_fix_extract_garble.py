import ast
import os
import time

APP_PATH = os.environ.get('MCP_APP') or './app.py'

def read_text(p):
    with open(p, 'r', encoding='utf-8') as f:
        return f.read()

def write_text(p, t):
    with open(p, 'w', encoding='utf-8') as f:
        f.write(t)

def backup(p, t):
    ts = time.strftime('%Y%m%d-%H%M%S')
    bak = p + '.bak.' + ts
    write_text(bak, t)
    return bak

def find_func_span(src, func_name):
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            if getattr(node, 'end_lineno', None) is None:
                raise SystemExit('ast end_lineno not available; need Python 3.8+')
            return node.lineno, node.end_lineno
    return None, None

def main():
    src = read_text(APP_PATH)
    if 'MCP_WEB_ANSWER_POLICY_V2' not in src:
        raise SystemExit('Expected V2 web_answer already present; abort to avoid wrong base.')

    bak = backup(APP_PATH, src)
    lines = src.splitlines(True)

    s, e = find_func_span(src, 'web_answer')
    if not s:
        raise SystemExit('web_answer not found')

    # Replace the body by editing a few specific lines via string operations:
    # We'll rebuild web_answer entirely by reusing existing V2 text but adding:
    # - skip open when relevance_low True
    # - garble detection fallback
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
        "    # Only open when snippet is too short or clearly truncated, AND not low relevance\n"
        "    snippet_short = True if (len(best_snippet or '') < 120) else False\n"
        "    snippet_trunc = True if ((best_snippet or '').strip().endswith('...') or (best_snippet or '').strip().endswith('…')) else False\n"
        "    do_open = True if (need_open and (not relevance_low) and best_url and (snippet_short or snippet_trunc)) else False\n\n"
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
        "    # Garble guard: if extracted text looks like mojibake, fall back to snippet\n"
        "    def _looks_garbled(s):\n"
        "        x = s or ''\n"
        "        if not x:\n"
        "            return False\n"
        "        bad_hits = 0\n"
        "        for tok in ['Ã', 'Â', 'â', 'ï', '�', 'ç¥', 'ä1', 'ï1']:\n"
        "            if tok in x:\n"
        "                bad_hits += 1\n"
        "        return True if bad_hits >= 2 else False\n\n"
        "    use_extract = True if (extract_text and (not _looks_garbled(extract_text))) else False\n"
        "    answer = extract_text if use_extract else best_snippet\n\n"
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

    new_lines = lines[:s-1] + [new_func] + lines[e:]
    write_text(APP_PATH, ''.join(new_lines))

    print('patched_path=' + APP_PATH)
    print('backup_path=' + bak)
    print('web_answer_span=' + str(s) + '-' + str(e))

if __name__ == '__main__':
    main()
