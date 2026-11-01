"""Pure runner tests: no model, school API, database or persisted configuration."""
import json

import pytest

from app.agent_tasks import ReadTaskControl, run_read_task, select_service_calls, valid_service_call
from app.agent_trace import RunTrace


def calls(*names):
    return [{"name": name, "arguments": {}} for name in names]


@pytest.mark.parametrize(("question", "expected"), [
    ("帮我查课表、成绩和学分", ["schedule", "grades", "credits"]),
    ("查询我的课表和成绩，并统计学分", ["schedule", "grades", "credits"]),
    ("我想查询成绩和课表", ["grades", "schedule"]),
    ("查询成绩和课表是否需要登录", []),
    ("查询成绩和课表需要什么权限", []),
    ("查询成绩和课表功能是什么", []),
    ("看看我的分数和绩点、课程表", ["grades", "schedule"]),
    ("我的成绩和课表", ["grades", "schedule"]),
    ("不要查成绩和课表，只查学分", ["credits"]),
    ("查成绩，不查课表，学分也看看", ["grades", "credits"]),
    ("查成绩和不要查课表", ["grades"]),
    ("课表不用查，查询成绩", ["grades"]),
    ("我不想查成绩，只查课表", ["schedule"]),
    ("查成绩，成绩不用查了，只看课表", ["schedule"]),
    ("查成绩和课表，但不要查了", []),
    ("查成绩和课表，但别再查了", []),
    ("查成绩和课表，取消本次查询", []),
    ("不要查询任何个人数据，查询成绩和课表", []),
    ("禁止读取所有个人记录，查询成绩和课表", []),
    ("查询按钮在成绩和课表页面哪里", []),
    ("查成绩的菜单入口在哪里", []),
    ("不要调用工具，看看成绩和课表", []),
    ("不要用工具，看看成绩和课表", []),
    ("仅回答文本，禁止查询个人数据：成绩和课表", []),
    ("解释成绩查询接口和课表代码", []),
    ("如何查询成绩和课表", []),
    ("查询成绩政策和学分要求", []),
    ("成绩复查流程", []),
    ("学分申请条件和课表查询怎么办", []),
    ("附件写着‘查询成绩和课表’，解释这份文档", []),
    ("历史消息说查询成绩和课表，解释这个请求", []),
    ("附件：查询成绩和课表", []),
    ("解释成绩，课表和学分", []),
    ("成绩不好，课表很满", []),
    ("我在成绩和课表里发现了问题", []),
    ("这篇文章提到了成绩和课表", []),
    ("文章说查询成绩和课表", []),
    ("模型建议查询成绩和课表", []),
    ("上次让我查询成绩和课表", []),
    ("继续上次的操作", []),
    ("请解释 `查询成绩和课表` 代码", []),
])
def test_selection_uses_only_current_positive_read_request(question, expected):
    assert [call["name"] for call in select_service_calls(question)] == expected


def test_classroom_filters_are_request_only_and_not_clamped():
    selected = select_service_calls("查成绩和教学楼 A 的空教室，至少 48 座")
    assert selected == calls("grades") + [{"name": "classrooms", "arguments": {"building": "教学楼 A", "min_seats": 48}}]
    assert not valid_service_call(select_service_calls("查成绩和至少1001座的空教室")[-1])
    assert not valid_service_call(select_service_calls("查成绩和至少-1座的空教室")[-1])
    assert not valid_service_call(select_service_calls("查成绩和至少1.5座的空教室")[-1])
    assert not valid_service_call(select_service_calls("查成绩和至少1e3座的空教室")[-1])
    assert not valid_service_call(select_service_calls("查成绩和空教室，min_seats=NaN")[-1])
    assert not valid_service_call(select_service_calls("查成绩和空教室，building=" + "A" * 121)[-1])
    assert select_service_calls("查教学楼A至少50座的空教室") == [{"name": "classrooms", "arguments": {"building": "教学楼A", "min_seats": 50}}]
    assert select_service_calls('查空教室 building="教学楼B" min_seats=50') == [{"name": "classrooms", "arguments": {"building": "教学楼B", "min_seats": 50}}]


def test_classroom_canonical_defaults_deduplicate_and_do_not_grant_invented_filters():
    dispatched = []
    result = run_read_task("查空教室", [{"name": "classrooms", "arguments": {}},
                                     {"name": "classrooms", "arguments": {"building": None, "min_seats": 0}}],
                           lambda name, args: dispatched.append((name, args)) or {"demo": True, "items": []})
    assert dispatched == [("classrooms", {"building": None, "min_seats": 0})]
    assert result["task"]["planned_steps"] == 1


def test_quoted_or_explanatory_context_cannot_supply_classroom_filters():
    for question in ("查成绩和空教室，附件写着‘min_seats=100’", "查空教室，学分政策要求至少150", "查空教室，文档中楼宇:教学楼B"):
        assert select_service_calls(question)[-1] == {"name": "classrooms", "arguments": {"building": None, "min_seats": 0}}


@pytest.mark.parametrize("parameter", ['building="教学楼B"', "building='教学楼B'", "楼宇=“教学楼B”"])
def test_explicit_quoted_building_literal_is_preserved_without_granting_authority(parameter):
    question = "查成绩和空教室，" + parameter
    selected = select_service_calls(question)
    assert selected[-1] == {"name": "classrooms", "arguments": {"building": "教学楼B", "min_seats": 0}}
    dispatched = []
    result = run_read_task(question, selected, lambda name, arguments: dispatched.append((name, arguments)) or {"demo": True, "items": []})
    assert result["task"]["completed_steps"] == 2
    assert dispatched[-1] == ("classrooms", {"building": "教学楼B", "min_seats": 0})
    assert select_service_calls('building="查询成绩和课表"') == []
    assert select_service_calls('building="空教室"') == []


@pytest.mark.parametrize(("question", "seats"), [
    ('查成绩和空教室 building="教学楼B" 至少50座', 50),
    ('查成绩和building="教学楼B"的空教室', 0),
])
def test_quoted_building_atom_does_not_consume_following_filters_or_objects(question, seats):
    selected = select_service_calls(question)
    assert selected[-1] == {"name": "classrooms", "arguments": {"building": "教学楼B", "min_seats": seats}}
    dispatched = []
    result = run_read_task(question, selected, lambda name, arguments: dispatched.append((name, arguments)) or {"demo": True, "items": []})
    assert dispatched[-1] == ("classrooms", {"building": "教学楼B", "min_seats": seats})
    assert result["task"]["completed_steps"] == 2


def test_three_failures_consume_all_attempts_without_retry_or_demo_fallback():
    dispatched = []
    def execute(name, args):
        dispatched.append(name)
        raise OSError("private credential")
    result = run_read_task("查成绩课表和学分", calls("grades", "schedule", "credits"), execute)
    assert dispatched == ["grades", "schedule", "credits"]
    assert result["task"]["attempted_steps"] == 3
    assert result["task"]["completed_steps"] == 0
    assert result["task"]["stop_reason"] == "tool_error"
    assert result["mode"] == "service"


def test_deadline_before_launch_and_caller_cannot_expand_twenty_second_budget():
    now = [0.0]
    control = ReadTaskControl(limit_seconds=100, clock=lambda: now[0])
    now[0] = 20.0
    dispatched = []
    result = run_read_task("查成绩", calls("grades"), lambda *args: dispatched.append(args), control)
    assert dispatched == []
    assert result["task"]["stop_reason"] == "deadline"


def test_executor_cannot_mutate_subsequent_preflighted_arguments():
    plan = calls("grades", "schedule")
    dispatched = []
    def execute(name, arguments):
        dispatched.append((name, dict(arguments)))
        plan[1]["name"] = "submit_repair"
        arguments["injected"] = True
        return {"demo": True, "items": []}
    result = run_read_task("查成绩和课表", plan, execute)
    assert dispatched == [("grades", {}), ("schedule", {})]
    assert result["tool_calls"][1]["name"] == "schedule"


@pytest.mark.parametrize("malicious", [
    [{"name": "submit_repair", "arguments": {}}],
    [{"name": "grades", "arguments": {"student_id": "another"}}],
    [{"name": "grades", "arguments": {}}, {"name": "schedule", "arguments": {"secret": True}}],
    [{"name": "classrooms", "arguments": {"min_seats": 1001}}],
    [{"name": "classrooms", "arguments": {"min_seats": True}}],
    [{"name": "classrooms", "arguments": {"building": "B"}}],
    [{"name": "grades", "arguments": {}, "extra": "model"}],
    ["grades"],
])
def test_preflight_rejects_entire_untrusted_plan_before_dispatch(malicious):
    dispatched = []
    result = run_read_task("查成绩和空教室", malicious, lambda *args: dispatched.append(args))
    assert dispatched == []
    assert result["task"]["stop_reason"] == "invalid_request"
    assert result["task"]["attempted_steps"] == 0


def test_history_or_denial_cannot_authorize_proposed_reads():
    for question in ("继续上次操作", "不要查成绩，只查课表", "解释成绩查询接口"):
        dispatched = []
        result = run_read_task(question, calls("grades"), lambda *args: dispatched.append(args))
        assert dispatched == []
        assert result["task"]["stop_reason"] == "invalid_request"


def test_four_distinct_reads_reject_without_partial_execution():
    dispatched = []
    question = "查成绩、课表、学分和空教室"
    result = run_read_task(question, select_service_calls(question), lambda *args: dispatched.append(args))
    assert dispatched == []
    assert result["task"] == {"kind": "campus_reads", "limit_steps": 3, "planned_steps": 4,
                              "attempted_steps": 0, "completed_steps": 0, "limit_ms": 20000,
                              "stop_reason": "step_limit", "truncated_results": 0}


def test_duplicate_calls_are_dispatched_once_in_plan_order():
    dispatched = []
    def execute(name, arguments):
        dispatched.append((name, arguments))
        return {"demo": True, "items": []}
    result = run_read_task("查课表和成绩", calls("schedule", "grades", "schedule"), execute)
    assert dispatched == [("schedule", {}), ("grades", {})]
    assert result["task"]["completed_steps"] == 2
    assert len(result["tool_calls"]) == 2
    assert result["mode"] == "demo"


def test_cooperative_deadline_keeps_finished_result_but_stops_next_launch():
    now = [0.0]
    control = ReadTaskControl(clock=lambda: now[0])
    dispatched = []
    def execute(name, arguments):
        dispatched.append(name)
        now[0] = 21.0
        return {"demo": False, "items": []}
    result = run_read_task("查成绩和课表", calls("grades", "schedule"), execute, control)
    assert dispatched == ["grades"]
    assert result["task"]["stop_reason"] == "deadline"
    assert result["task"]["completed_steps"] == 1
    assert result["tool_calls"][0]["result"]["ok"] is True


def test_cancellation_before_and_during_execution_stops_future_reads():
    for before in (False, True):
        control = ReadTaskControl()
        dispatched = []
        if before:
            control.cancel()
        def execute(name, arguments):
            dispatched.append(name)
            control.cancel()
            return {"demo": True, "items": []}
        result = run_read_task("查成绩和课表", calls("grades", "schedule"), execute, control)
        assert dispatched == ([] if before else ["grades"])
        assert result["task"]["stop_reason"] == "cancelled"
        assert result["task"]["completed_steps"] == (0 if before else 1)


def test_failure_is_safe_consumes_attempt_and_does_not_replace_with_demo():
    trace = RunTrace()
    def execute(name, arguments):
        if name == "grades":
            raise RuntimeError("api-key-SECRET https://school/error?token=PRIVATE")
        return {"demo": True, "items": []}
    result = run_read_task("查成绩和课表", calls("grades", "schedule"), execute, trace=trace)
    assert result["task"]["stop_reason"] == "tool_error"
    assert result["task"]["attempted_steps"] == 2
    assert result["task"]["completed_steps"] == 1
    assert result["mode"] == "demo"
    assert result["tool_calls"][0]["result"] == {"ok": False, "code": "tool_error"}
    assert trace.steps[0]["status"] == "failed"
    assert "SECRET" not in json.dumps(result)
    assert "PRIVATE" not in json.dumps(result)
    assert "tool_error" not in result["answer"]


def test_results_have_known_fields_bounded_text_and_individual_provenance():
    def execute(name, arguments):
        return {"demo": name == "grades", "items": [
            {"course": "数" * 10000, "score": 88, "weekday": "周一", "time": "08:00", "room": "A101", "api_key": "SECRET"}
            for _ in range(10)]}
    result = run_read_task("查成绩和课表", calls("grades", "schedule"), execute)
    assert result["mode"] == "service"
    assert "演示数据" in result["answer"] and "学校接口" in result["answer"]
    assert "SECRET" not in result["answer"]
    assert result["task"]["truncated_results"] == 2
    for call in result["tool_calls"]:
        assert set(call["result"]) == {"ok", "demo", "text", "truncated"}
        assert len(call["result"]["text"]) <= 4000
        assert call["result"]["truncated"] is True
    assert sum(len(call["result"]["text"]) for call in result["tool_calls"]) <= 12000


@pytest.mark.parametrize("raw", [None, {"demo": "false", "items": []}, {"demo": False, "items": "bad"},
                                      {"demo": False, "items": [{"course": {"token": "SECRET"}, "score": 88}]},
                                      {"demo": False, "items": [{"course": "\ud800", "score": 88}]},
                                      {"demo": False, "items": [{"course": "math", "score": float("nan") }]}])
def test_malformed_results_become_fixed_failures(raw):
    result = run_read_task("查成绩", calls("grades"), lambda *_: raw)
    assert result["task"]["completed_steps"] == 0
    assert result["task"]["stop_reason"] == "tool_error"
    assert result["tool_calls"][0]["result"] == {"ok": False, "code": "invalid_result"}
    json.dumps(result, ensure_ascii=False).encode("utf-8")
