import re

p = "app.py"
s = open(p, "r", encoding="utf-8").read()
orig = s

# 1) 缺省日历实体提示：日历 -> 日程（保持意思一致）
s = s.replace("未配置默认日历实体。请设置环境变量 HA_DEFAULT_CALENDAR_ENTITY，或直接用 ha_calendar_events(entity_id,start,end) 调用。",
              "未配置默认日程实体。请设置环境变量 HA_DEFAULT_CALENDAR_ENTITY，或直接用 ha_calendar_events(entity_id,start,end) 调用。")

# 2) structured_calendar 成功摘要：日历事件 -> 日程
s = s.replace("已获取日历事件（", "已获取日程（")
s = s.replace("），区间 ", "），时间范围 ")
s = s.replace("，共 ", "，共 ")
s = s.replace(" 条。", " 条日程。")

# 3) 如果你的代码里仍出现“无法获取日历事件”，也统一改成“无法获取日程”
s = s.replace("无法获取日历事件。", "无法获取日程。")

if s == orig:
    raise RuntimeError("No changes applied (maybe already patched).")

open(p, "w", encoding="utf-8").write(s)
print("patched_ok=1")
