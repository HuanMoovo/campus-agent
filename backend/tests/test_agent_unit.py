"""Offline tests for the bounded agent; web/database/model transports are substituted."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / "app"


def module(name, **values):
    result = ModuleType(name)
    result.__dict__.update(values)
    return result


settings = SimpleNamespace(qwen_api_key="", qwen_base_url="https://qwen.example/v1", qwen_model="qwen3",
                           deepseek_api_key="", deepseek_base_url="https://deepseek.example/v1", deepseek_model="deepseek")
retriever = SimpleNamespace(search=lambda db, question: [])
stubs = {
    "_campus_agent_test": module("_campus_agent_test", __path__=[str(APP)]),
    "_campus_agent_test.config": module("_campus_agent_test.config", get_settings=lambda: settings),
    "_campus_agent_test.rag": module("_campus_agent_test.rag", knowledge_index=retriever),
    "_campus_agent_test.models": module("_campus_agent_test.models", Repair=object),
    "_campus_agent_test.schemas": module("_campus_agent_test.schemas", RepairCreate=object),
    "sqlalchemy": module("sqlalchemy", select=lambda *args, **kwargs: None),
    "sqlalchemy.orm": module("sqlalchemy.orm", Session=object),
    "httpx": module("httpx", HTTPError=type("HTTPError", (Exception,), {})),
}

with patch.dict(sys.modules, stubs):
    spec = importlib.util.spec_from_file_location("_campus_agent_test.agent", APP / "agent.py")
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)


class AgentTests(unittest.TestCase):
    def state(self, question):
        return {"question": question, "history": [], "requested_model": "auto"}

    def test_policy_questions_do_not_query_personal_data(self):
        for question in ("成绩复查流程", "学分认定政策", "如何申请空教室"):
            self.assertEqual(agent.plan(self.state(question))["intent"], "knowledge")

    def test_explicit_service_query_selects_read_only_tool(self):
        state = self.state("查询我的成绩")
        state.update(agent.plan(state))
        state.update(agent.execute_service(state))
        result = agent.respond(state)
        self.assertEqual(state["tool_calls"][0]["name"], "grades")
        self.assertIn("演示数据", result["answer"])

    def test_classroom_parameter_extraction_and_filter(self):
        state = self.state("查教学楼A至少50座的空教室")
        state.update(agent.plan(state))
        result = agent.execute_service(state)
        self.assertEqual(result["tool_calls"][0]["arguments"]["min_seats"], 50)
        self.assertEqual([room["room"] for room in result["tool_result"]["items"]], ["A208"])

    def test_unregistered_or_malformed_model_calls_cannot_execute(self):
        proposals = [
            {"tool_calls": [{"function": {"name": "delete_database", "arguments": "{}"}}]},
            {"tool_calls": [{"function": {"name": "grades", "arguments": '{"student_id":"another-user"}'}}]},
            {"tool_calls": [{"function": {"name": "grades", "arguments": "invalid json"}}]},
            {"tool_calls": [{"function": {"name": [], "arguments": "{}"}}]},
        ]
        for proposal in proposals:
            with self.subTest(proposal=proposal), patch.object(agent, "completion", return_value=proposal):
                self.assertEqual(agent.plan(self.state("你好"))["intent"], "knowledge")

    def test_only_first_tool_can_be_selected(self):
        proposal = {"tool_calls": [{"function": {"name": "schedule", "arguments": "{}"}}, {"function": {"name": "grades", "arguments": "{}"}}]}
        with patch.object(agent, "completion", return_value=proposal):
            self.assertEqual(agent.plan(self.state("查课表和成绩"))["intent"], "schedule")

    def test_empty_retrieval_does_not_invent_policy(self):
        result = agent.respond({**self.state("校园未知事项"), "intent": "knowledge", "sources": []})
        self.assertIn("暂未找到可靠依据", result["answer"])

    def test_follow_up_includes_previous_topic_in_retrieval(self):
        state = {**self.state("需要什么材料？"), "history": [{"role": "user", "content": "如何补办校园一卡通"}]}
        with patch.object(retriever, "search", return_value=[]) as search:
            agent.make_knowledge_node(None)(state)
        self.assertIn("校园一卡通", search.call_args.args[1])

    def test_repair_is_not_an_automatic_tool(self):
        self.assertNotIn("repairs", [tool["function"]["name"] for tool in agent.TOOLS])
        self.assertEqual(agent.plan(self.state("帮我报修灯泡"))["intent"], "knowledge")

    def test_model_routing_respects_explicit_choice_and_configuration(self):
        with patch.object(settings, "qwen_api_key", "q"), patch.object(settings, "deepseek_api_key", "d"):
            self.assertEqual(agent.choose_model("auto", "分析比较两个政策")[0], "deepseek")
            self.assertEqual(agent.choose_model("auto", "借书")[0], "qwen")
            self.assertEqual(agent.choose_model("qwen", "分析比较")[0], "qwen")
        self.assertIsNone(agent.choose_model("auto"))


if __name__ == "__main__":
    unittest.main()
