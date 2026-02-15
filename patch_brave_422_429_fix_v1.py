#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time

APP = "app.py"

def backup(path):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = "{0}.bak.brave_422_429_fix_{1}".format(path, ts)
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    with open(bak, "w", encoding="utf-8") as f:
        f.write(src)
    return bak, src

def patch_web_search_force_en(lines):
    """
    After: lang_used = _mcp__auto_language(q, language)
    Insert: if not zh and has latin letters -> lang_used="en"
    Also cap kk <= 5 instead of 10.
    """
    changed = False

    # (A) cap kk
    for i in range(len(lines)):
        if lines[i].strip() == "if kk > 10:" and i + 1 < len(lines) and lines[i+1].strip() == "kk = 10":
            lines[i] = lines[i].replace("10", "5")
            lines[i+1] = lines[i+1].replace("10", "5")
            changed = True
            break

    # (B) force english for non-zh queries
    for i in range(len(lines)):
        if lines[i].strip() == "lang_used = _mcp__auto_language(q, language)":
            # already patched?
            block_text = "".join(lines[i+1:i+18])
            if "force English for non-zh queries" in block_text:
                return changed

            indent = lines[i].split("l")[0]  # preserve leading spaces
            ins = []
            ins.append(indent + "# force English for non-zh queries (avoid Brave 422 with zh params on latin query)\n")
            ins.append(indent + "try:\n")
            ins.append(indent + "    if (not _mcp__has_zh(q)) and re.search(r\"[A-Za-z]\", q or \"\"):\n")
            ins.append(indent + "        lang_used = \"en\"\n")
            ins.append(indent + "except Exception:\n")
            ins.append(indent + "    pass\n")
            lines[i+1:i+1] = ins
            changed = True
            break

    return changed

def patch_brave_headers_and_retry(lines):
    """
    In _searxng_search (Brave backend):
      - add Cache-Control header
      - replace the 3-line get/raise/json with retry/fallback block
    """
    changed = False

    # 1) add Cache-Control if missing in headers dict
    for i in range(len(lines)):
        if lines[i].strip() == '"Accept-Encoding": "gzip",':
            # look ahead a little to see if Cache-Control already exists
            look = "".join(lines[i:i+15]).lower()
            if "cache-control" in look:
                break
            indent = lines[i].split('"')[0]
            lines.insert(i+1, indent + '"Cache-Control": "no-cache",\n')
            changed = True
            break

    # 2) replace resp=get / raise / json block
    for i in range(len(lines)):
        if lines[i].strip().startswith("resp = requests.get(") and "api_url" in lines[i] and "params=params" in lines[i]:
            # already patched?
            look = "".join(lines[i:i+40])
            if "_do_get(" in look and "status_code == 429" in look:
                return changed

            # expect next lines: resp.raise_for_status(); j = resp.json()
            if i + 2 >= len(lines):
                continue
            if lines[i+1].strip() != "resp.raise_for_status()":
                continue
            if lines[i+2].strip() != "j = resp.json()":
                continue

            indent = lines[i].split("r")[0]

            new_block = []
            new_block.append(indent + "def _do_get(p, h):\n")
            new_block.append(indent + "    return requests.get(api_url, params=p, headers=h, timeout=timeout_s)\n")
            new_block.append("\n")
            new_block.append(indent + "resp = _do_get(params, headers)\n")
            new_block.append("\n")
            new_block.append(indent + "if resp.status_code == 429:\n")
            new_block.append(indent + "    ra = (resp.headers.get(\"Retry-After\") or \"\").strip()\n")
            new_block.append(indent + "    wait_s = 1.2\n")
            new_block.append(indent + "    try:\n")
            new_block.append(indent + "        wait_s = float(ra)\n")
            new_block.append(indent + "    except Exception:\n")
            new_block.append(indent + "        pass\n")
            new_block.append(indent + "    if wait_s < 0.5:\n")
            new_block.append(indent + "        wait_s = 0.5\n")
            new_block.append(indent + "    if wait_s > 2.0:\n")
            new_block.append(indent + "        wait_s = 2.0\n")
            new_block.append(indent + "    try:\n")
            new_block.append(indent + "        import time as _time\n")
            new_block.append(indent + "        _time.sleep(wait_s)\n")
            new_block.append(indent + "    except Exception:\n")
            new_block.append(indent + "        pass\n")
            new_block.append(indent + "    resp = _do_get(params, headers)\n")
            new_block.append("\n")
            new_block.append(indent + "if resp.status_code == 422:\n")
            new_block.append(indent + "    # fallback: most conservative lang/ui + drop extra_snippets\n")
            new_block.append(indent + "    p2 = dict(params)\n")
            new_block.append(indent + "    p2[\"search_lang\"] = \"en\"\n")
            new_block.append(indent + "    p2[\"ui_lang\"] = \"en-US\"\n")
            new_block.append(indent + "    if \"extra_snippets\" in p2:\n")
            new_block.append(indent + "        try:\n")
            new_block.append(indent + "            del p2[\"extra_snippets\"]\n")
            new_block.append(indent + "        except Exception:\n")
            new_block.append(indent + "            pass\n")
            new_block.append(indent + "    h2 = dict(headers)\n")
            new_block.append(indent + "    h2[\"Accept-Language\"] = \"en-US\"\n")
            new_block.append(indent + "    h2[\"Cache-Control\"] = \"no-cache\"\n")
            new_block.append(indent + "    resp = _do_get(p2, h2)\n")
            new_block.append("\n")
            new_block.append(indent + "resp.raise_for_status()\n")
            new_block.append(indent + "j = resp.json()\n")

            # replace 3 lines with new block
            lines[i:i+3] = new_block
            changed = True
            break

    return changed

def main():
    bak, src = backup(APP)
    lines = src.splitlines(True)

    c1 = patch_web_search_force_en(lines)
    c2 = patch_brave_headers_and_retry(lines)

    if not (c1 or c2):
        print("NOTE: no changes applied (already patched?)")
        print("Backup:", bak)
        return

    with open(APP, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print("OK patched:", APP)
    print("Backup:", bak)

if __name__ == "__main__":
    main()
