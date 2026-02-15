import re

PATH = "app.py"

with open(PATH, "r", encoding="utf-8") as f:
    s = f.read()

orig = s

# 1) 确保有 dt_date 别名导入（避免被函数内局部变量 date 覆盖）
has_dt_date = re.search(r'^\s*from\s+datetime\s+import\s+.*\bdate\s+as\s+dt_date\b', s, flags=re.M)
has_plain_dt_date = re.search(r'^\s*from\s+datetime\s+import\s+date\s+as\s+dt_date\s*$', s, flags=re.M)

if (not has_dt_date) and (not has_plain_dt_date):
    # 找到 "from datetime import ..." 行，在其后插入
    m = re.search(r'^\s*from\s+datetime\s+import\s+.*$', s, flags=re.M)
    if m:
        insert_pos = m.end()
        s = s[:insert_pos] + "\nfrom datetime import date as dt_date\n" + s[insert_pos:]
    else:
        # 极端兜底：插到文件开头 import 区域后
        m2 = re.search(r'^(?:import\s+[^\n]+\n)+', s, flags=re.M)
        if m2:
            insert_pos = m2.end()
            s = s[:insert_pos] + "from datetime import date as dt_date\n" + s[insert_pos:]
        else:
            s = "from datetime import date as dt_date\n" + s

# 2) 只替换 base_d 那一行的 date(...) -> dt_date(...)
#    这样不会误伤其它地方把 date 当变量用的逻辑
s2 = re.sub(r'(\bbase_d\s*=\s*)date\(', r'\1dt_date(', s)

patched = 1 if s2 != orig else 0

with open(PATH, "w", encoding="utf-8") as f:
    f.write(s2)

print("patched_ok=" + str(patched))
