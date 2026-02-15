import re

P = "app.py"
s = open(P, "r", encoding="utf-8").read()

if "_ug_extract_readable_text" not in s:
    raise SystemExit("cannot find _ug_extract_readable_text() in app.py")

# 1) 确保导入 unicodedata（函数内导入也行，这里优先函数内注入，避免全局改动）
# 2) 在 _ug_extract_readable_text 里，在 out = out.strip() 之前插入清洗逻辑

# 找到函数体末尾 out.strip() 的位置
m = re.search(r"(?ms)(def\s+_ug_extract_readable_text\s*\(.*?\)\s*:\s*)(.*?)\n(\s*)return\s+out\s*\n", s)
if not m:
    raise SystemExit("failed to locate _ug_extract_readable_text() block")

func_head = m.group(1)
func_body = m.group(2)
indent = m.group(3)

# 避免重复打补丁
if "unicodedata" in func_body and "_ug_clean_unicode" in func_body:
    print("patch already applied")
    raise SystemExit(0)

inject = r'''
        import unicodedata as _ud

        def _ug_clean_unicode(x: str) -> str:
            if not x:
                return ""
            # Normalize first
            x = _ud.normalize("NFKC", x)

            # Drop format chars (zero-width etc.)
            x = "".join(ch for ch in x if _ud.category(ch) != "Cf")

            # Replace common weird spaces
            x = x.replace("\u00a0", " ")   # NBSP
            x = x.replace("\u202f", " ")   # NNBSP
            x = x.replace("\u2007", " ")   # figure space
            x = x.replace("\u2009", " ")   # thin space
            x = x.replace("\u200a", " ")   # hair space
            x = x.replace("\ufeff", "")    # BOM

            # Collapse whitespace aggressively for excerpt usage
            x = _re.sub(r"\s+", " ", x).strip()
            return x

        out = _ug_clean_unicode(out)
'''

# 在 out = out.strip() 之前插入（如果没有 out.strip，就在 return out 之前插入）
if re.search(r"(?m)^\s*out\s*=\s*out\.strip\(\)\s*$", func_body):
    func_body2 = re.sub(
        r"(?m)^\s*out\s*=\s*out\.strip\(\)\s*$",
        "        out = out.strip()\n" + inject.rstrip("\n"),
        func_body,
        count=1
    )
else:
    func_body2 = func_body + "\n" + inject

new_block = func_head + func_body2 + "\n" + indent + "return out\n"
s2 = s[:m.start()] + new_block + s[m.end():]

open(P, "w", encoding="utf-8").write(s2)
print("patched: unicode cleanup + whitespace collapse in _ug_extract_readable_text")
