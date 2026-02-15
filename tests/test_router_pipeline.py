import unittest

import router_pipeline as rp


class RouterPipelineTests(unittest.TestCase):
    def test_should_handoff_control_true(self):
        r = rp.should_handoff_control(
            "打开客厅灯",
            is_home_control_like_intent=lambda s: True,
            is_music_control_query=lambda s: False,
        )
        self.assertTrue(r)

    def test_should_handoff_control_false_for_music(self):
        r = rp.should_handoff_control(
            "播放周杰伦",
            is_home_control_like_intent=lambda s: True,
            is_music_control_query=lambda s: True,
        )
        self.assertFalse(r)

    def test_handle_default_fallback_smalltalk(self):
        ret = rp.handle_default_fallback(
            "你好",
            "zh",
            False,
            is_obvious_smalltalk=lambda s: True,
            smalltalk_reply=lambda s, l: "你好呀",
            is_poi_intent=lambda s: False,
            poi_answer=lambda s, l: "",
            web_search_answer=lambda s, l, limit: ("", {}),
            news_extract_limit=lambda s, d: d,
            has_strong_lookup_intent=lambda s: False,
            is_life_advice_intent=lambda s: False,
            life_advice_fallback=lambda s, l: "",
        )
        self.assertEqual(ret.get("route_type"), "open_domain")
        self.assertEqual(ret.get("final"), "你好呀")

    def test_handle_default_fallback_poi(self):
        ret = rp.handle_default_fallback(
            "Bunnings Doncaster 营业时间",
            "zh",
            True,
            is_obvious_smalltalk=lambda s: False,
            smalltalk_reply=lambda s, l: "",
            is_poi_intent=lambda s: True,
            poi_answer=lambda s, l: "poi ok",
            web_search_answer=lambda s, l, limit: ("", {}),
            news_extract_limit=lambda s, d: d,
            has_strong_lookup_intent=lambda s: False,
            is_life_advice_intent=lambda s: False,
            life_advice_fallback=lambda s, l: "",
        )
        self.assertEqual(ret.get("route_type"), "semi_structured_poi")
        self.assertEqual(ret.get("final"), "poi ok")
        self.assertTrue("data" in ret)

    def test_handle_default_fallback_web_then_life_advice(self):
        ret = rp.handle_default_fallback(
            "我有点累怎么办",
            "zh",
            False,
            is_obvious_smalltalk=lambda s: False,
            smalltalk_reply=lambda s, l: "smalltalk",
            is_poi_intent=lambda s: False,
            poi_answer=lambda s, l: "",
            web_search_answer=lambda s, l, limit: ("", {}),
            news_extract_limit=lambda s, d: d,
            has_strong_lookup_intent=lambda s: True,
            is_life_advice_intent=lambda s: True,
            life_advice_fallback=lambda s, l: "先休息十分钟",
        )
        self.assertEqual(ret.get("route_type"), "open_domain")
        self.assertEqual(ret.get("final"), "先休息十分钟")


if __name__ == "__main__":
    unittest.main(verbosity=2)
