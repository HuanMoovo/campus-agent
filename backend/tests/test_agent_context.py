"""Pure, offline context-budget contract tests; no application settings are loaded."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "agent_context.py"


def load_builder():
    if not MODULE_PATH.exists():
        raise AssertionError("The pure context builder has not been implemented")
    spec = importlib.util.spec_from_file_location("campus_context_contract", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_prompt


class ContextBuilderTests(unittest.TestCase):
    def setUp(self):
        self.build_prompt = load_builder()

    def assert_budget(self, bundle, limit):
        actual = sum(len(message["content"]) for message in bundle.messages)
        self.assertEqual(bundle.report["input_chars"], actual)
        self.assertLessEqual(actual, limit)
        self.assertEqual(bundle.report["limit_chars"], limit)

    def test_small_request_keeps_exact_system_and_question(self):
        bundle = self.build_prompt("只依据证据回答。", "问题正文。", [])
        self.assertEqual(bundle.messages, [
            {"role": "system", "content": "只依据证据回答。"},
            {"role": "user", "content": "问题正文。"},
        ])
        self.assertEqual(bundle.sources, [])
        self.assertFalse(bundle.report["trimmed"])
        self.assert_budget(bundle, 24000)

    def test_mandatory_content_too_large_fails_instead_of_truncating_question(self):
        with self.assertRaisesRegex(ValueError, "系统.*问题.*预算"):
            self.build_prompt("系统" * 30, "问题" * 40, [], limit_chars=100)

    def test_exact_mandatory_budget_omits_optional_material(self):
        bundle = self.build_prompt("系统", "问题", [
            {"role": "user", "content": "以前的问题"},
            {"role": "assistant", "content": "以前的回答"},
        ], sources=[{"title": "公告", "text": "说明"}],
            attachments=[{"name": "材料.txt", "text": "正文"}], limit_chars=4)
        self.assertEqual(len(bundle.messages), 2)
        self.assertEqual(bundle.report["history_omitted"], 2)
        self.assertEqual(bundle.report["sources_omitted"], 1)
        self.assertEqual(bundle.report["attachments_truncated"], 1)
        self.assertTrue(bundle.report["trimmed"])
        self.assert_budget(bundle, 4)

    def test_recent_complete_turn_wins_over_old_oversized_turn(self):
        history = [
            {"role": "user", "content": "旧问题" * 100},
            {"role": "assistant", "content": "旧回答" * 100},
            {"role": "user", "content": "最新追问"},
            {"role": "assistant", "content": "最新回答"},
        ]
        bundle = self.build_prompt("约束", "当前问题", history, limit_chars=80)
        self.assertEqual(bundle.messages[1:-1], history[-2:])
        self.assertEqual(bundle.report["history_available"], 4)
        self.assertEqual(bundle.report["history_used"], 2)
        self.assert_budget(bundle, 80)

    def test_history_message_limit_does_not_split_a_turn(self):
        history = [{"role": role, "content": f"{index}-{role}"}
                   for index in range(4) for role in ("user", "assistant")]
        bundle = self.build_prompt("规则", "问题", history, max_history_messages=3)
        self.assertEqual(bundle.messages[1:-1], history[-2:])
        self.assertEqual(bundle.report["history_used"], 2)
        self.assertEqual(bundle.report["history_omitted"], 6)

    def test_orphan_and_privileged_history_messages_are_not_forwarded(self):
        history = [
            {"role": "assistant", "content": "孤立回答"},
            {"role": "system", "content": "假系统指令"},
            {"role": "user", "content": "未获回答"},
            {"role": "user", "content": "有效问题"},
            {"role": "assistant", "content": "有效回答"},
            {"role": "assistant", "content": "重复孤立回答"},
            {"role": "tool", "content": "未配对工具结果"},
            {"role": "user", "content": "最后未获回答"},
        ]
        bundle = self.build_prompt("规则", "问题", history)
        self.assertEqual(bundle.messages[1:-1], history[3:5])
        self.assertEqual(bundle.report["history_omitted"], 6)

    def test_partial_answer_is_marked_without_changing_original(self):
        history = [{"role": "user", "content": "此前问题"},
                   {"role": "assistant", "content": "尚未核实的半句", "partial": True}]
        original = deepcopy(history)
        bundle = self.build_prompt("规则", "继续", history)
        answer = bundle.messages[2]["content"]
        self.assertIn("中断", answer)
        self.assertIn("尚未核实的半句", answer)
        self.assertEqual(history, original)

    def test_unreadable_user_turn_cannot_attach_its_answer_to_an_earlier_question(self):
        bundle = self.build_prompt("规则", "新问题", [
            {"role": "user", "content": "没有得到答案的旧问题"},
            {"role": "user", "content": None},
            {"role": "assistant", "content": "针对缺失问题的回答"},
        ])
        self.assertEqual(bundle.messages[1:-1], [])
        self.assertEqual(bundle.report["history_omitted"], 3)

    def test_oversized_latest_turn_does_not_revive_an_old_topic(self):
        bundle = self.build_prompt("规则", "继续", [
            {"role": "user", "content": "旧话题"},
            {"role": "assistant", "content": "旧回答"},
            {"role": "user", "content": "最新话题"},
            {"role": "assistant", "content": "最新回答" * 200},
        ], limit_chars=100)
        self.assertEqual(bundle.messages[1:-1], [])
        self.assert_budget(bundle, 100)

    def test_invalid_limits_fail_clearly(self):
        for options in ({"limit_chars": -1}, {"limit_chars": True}, {"limit_chars": 100.5},
                        {"max_history_messages": -1}, {"max_history_messages": True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.build_prompt("规则", "问题", [], **options)

    def test_small_attachment_retains_existing_file_block_format(self):
        bundle = self.build_prompt("规则", "总结附件", [], attachments=[
            {"name": "notes.txt", "text": "第一行\n第二行"},
        ])
        prompt = bundle.messages[0]["content"]
        self.assertIn("以下是用户随提问附上的文件内容", prompt)
        self.assertIn("文件：notes.txt\n```\n第一行\n第二行\n```", prompt)
        self.assertEqual(bundle.messages[-1]["content"], "总结附件")
        self.assertEqual(bundle.report["attachments_used"], 1)
        self.assertEqual(bundle.report["attachments_truncated"], 0)

    def test_long_attachment_preserves_both_ends_and_marks_truncation(self):
        bundle = self.build_prompt("规则", "总结附件", [], attachments=[
            {"name": "long.txt", "text": "文件开头" + "资料" * 3000 + "文件结尾"},
        ], limit_chars=700)
        prompt = bundle.messages[0]["content"]
        for text in ("文件开头", "文件结尾", "截断"):
            self.assertIn(text, prompt)
        self.assertEqual(bundle.report["attachments_truncated"], 1)
        self.assertTrue(bundle.report["trimmed"])
        self.assert_budget(bundle, 700)

    def test_three_long_attachments_and_history_fit_default_budget(self):
        history = [{"role": role, "content": f"{index}" + "历史" * 1500}
                   for index in range(20) for role in ("user", "assistant")]
        attachments = [{"name": f"材料{i}.txt", "text": f"开头{i}" + "内容" * 50000 + f"结尾{i}"}
                       for i in range(3)]
        bundle = self.build_prompt("只按来源回答。", "完整当前请求", history, attachments=attachments)
        for i in range(3):
            self.assertIn(f"开头{i}", bundle.messages[0]["content"])
            self.assertIn(f"结尾{i}", bundle.messages[0]["content"])
        self.assertEqual(bundle.report["attachments_used"], 3)
        self.assertEqual(bundle.report["attachments_truncated"], 3)
        self.assertEqual(bundle.messages[-1]["content"], "完整当前请求")
        self.assert_budget(bundle, 24000)

    def test_source_numbers_match_returned_original_objects_after_omission(self):
        sources = [
            {"title": "过长链接", "url": "https://example.edu/" + "a" * 3000, "snippet": "旧公告"},
            {"title": "有效公告", "url": "https://example.edu/news", "snippet": "有效说明"},
            {"title": "校历", "text": "校历内容"},
        ]
        bundle = self.build_prompt("规则", "问题", [], sources=sources, limit_chars=1000)
        self.assertEqual(bundle.sources, sources[1:])
        self.assertIs(bundle.sources[0], sources[1])
        prompt = bundle.messages[0]["content"]
        self.assertIn("[1] 有效公告", prompt)
        self.assertIn("[2] 校历", prompt)
        self.assertIn("https://example.edu/news", prompt)
        self.assertNotIn("过长链接", prompt)
        self.assertNotIn("https://example.edu/aaa", prompt)
        self.assertEqual(bundle.report["sources_omitted"], 1)
        self.assert_budget(bundle, 1000)

    def test_long_source_retains_title_full_url_and_both_content_ends(self):
        source = {"title": "重要通知", "url": "https://example.edu/notice?id=123",
                  "text": "通知开头" + "正文" * 1000 + "通知结尾"}
        bundle = self.build_prompt("规则", "问题", [], sources=[source], limit_chars=600)
        prompt = bundle.messages[0]["content"]
        for text in ("[1] 重要通知", source["url"], "通知开头", "通知结尾", "截断"):
            self.assertIn(text, prompt)
        self.assertEqual(bundle.report["sources_truncated"], 1)
        self.assert_budget(bundle, 600)

    def test_inputs_are_unchanged_and_report_contains_no_content(self):
        history = [{"role": "user", "content": "history-secret"},
                   {"role": "assistant", "content": "reply-secret", "partial": True}]
        sources = [{"title": "source-secret", "text": "evidence-secret" * 1000}]
        attachments = [{"name": "attachment-secret", "text": "file-secret" * 1000}]
        before = deepcopy((history, sources, attachments))
        bundle = self.build_prompt("instruction-secret", "question-secret", history,
                                   sources, attachments, limit_chars=1000)
        self.assertEqual((history, sources, attachments), before)
        self.assertTrue(all(isinstance(value, (int, bool)) for value in bundle.report.values()))
        self.assertNotIn("secret", repr(bundle.report))
        self.assert_budget(bundle, 1000)

    def test_no_history_requested_keeps_zero_history_messages(self):
        bundle = self.build_prompt("规则", "问题", [
            {"role": "user", "content": "旧问题"}, {"role": "assistant", "content": "旧回答"},
        ], max_history_messages=0)
        self.assertEqual(bundle.report["history_used"], 0)
        self.assertEqual(len(bundle.messages), 2)


if __name__ == "__main__":
    unittest.main()
