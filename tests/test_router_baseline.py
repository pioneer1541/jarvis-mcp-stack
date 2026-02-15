import unittest
from unittest.mock import patch

import app
import router_helpers as rh


class RouterHelpersTests(unittest.TestCase):
    def test_home_control_like_intent(self):
        self.assertTrue(rh.is_home_control_like_intent("打开客厅灯"))
        self.assertTrue(rh.is_home_control_like_intent("turn on bedroom light"))
        self.assertFalse(rh.is_home_control_like_intent("今天世界新闻5条"))

    def test_smalltalk_and_lookup(self):
        self.assertTrue(rh.is_obvious_smalltalk("你好"))
        self.assertFalse(rh.is_obvious_smalltalk("查一下墨尔本停车费"))
        self.assertTrue(rh.has_strong_lookup_intent("查一下墨尔本停车费"))


class RouteRequestBaselineTests(unittest.TestCase):
    def test_control_guard_handoff(self):
        r = app._route_request_obj("打开客厅灯", language="zh")
        self.assertEqual(r.get("route_type"), "open_domain")
        self.assertIn("设备控制请求", str(r.get("final") or ""))

    def test_reminder_create_calendar_event(self):
        with patch.object(app, "_bills_ha_event_create", return_value={"ok": True}):
            r = app._route_request_obj("提醒我明天上午十点开会", language="zh")
        self.assertEqual(r.get("route_type"), "structured_calendar")
        self.assertIn("已为你添加日程", str(r.get("final") or ""))

    def test_reminder_water_smalltalk_plan(self):
        r = app._route_request_obj("提醒我多喝水", language="zh")
        self.assertEqual(r.get("route_type"), "open_domain")
        self.assertIn("每小时喝", str(r.get("final") or ""))

    def test_news_route_with_stubbed_digest(self):
        fake = {"ok": True, "final": "新闻A；新闻B"}
        with patch.object(app, "news_digest", return_value=fake):
            r = app._route_request_obj("今天世界新闻5条", language="zh")
        self.assertEqual(r.get("route_type"), "semi_structured_news")
        self.assertIn("新闻", str(r.get("final") or ""))

    def test_rag_disable(self):
        r = app._route_request_obj("不要查家庭资料库", language="zh")
        self.assertEqual(r.get("route_type"), "rag_disable")
        self.assertIn("不使用家庭资料库", str(r.get("final") or ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
