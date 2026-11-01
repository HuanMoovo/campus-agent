"""Deterministic, current-message-only campus read planning and bounded execution.

This module deliberately imports no model, service, database or filesystem code.
The supplied executor is the only dispatch boundary; results never become plans.
"""
from contextlib import nullcontext
import math
import re
from threading import Event
from time import monotonic


SERVICE_TERMS = {
    "grades": ("成绩", "分数", "绩点"),
    "schedule": ("课表", "课程表", "上课时间"),
    "credits": ("学分",),
    "classrooms": ("空教室", "自习室", "教室查询"),
}
LABELS = {"grades": "成绩", "schedule": "课表", "credits": "学分统计", "classrooms": "空教室"}
FIELDS = {
    "grades": ("course", "semester", "credits", "score"),
    "schedule": ("weekday", "time", "course", "room"),
    "classrooms": ("building", "room", "seats", "available"),
}
REQUIRED = {"grades": ("course", "score"), "schedule": ("weekday", "time", "course", "room"),
            "classrooms": ("building", "room", "seats")}
LIMIT_STEPS = 3
LIMIT_MS = 20000
RESULT_CHARS = 4000
TOTAL_CHARS = 12000
_DENIAL = re.compile(r"不要|不用|无需|别|禁止|不许|不必|不需要|不想|不允许|拒绝|停止|取消|不(?:要)?(?:查|查询|看|获取|调用|统计)")
_EXPLANATION = re.compile(r"解释|介绍|说明|政策|规定|要求|规则|流程|申请条件|接口|代码|文档|教程|示例|如何|怎么|区别|含义|什么意思|按钮|菜单|页面|入口|哪里|在哪|界面|点击|附件|历史消息|历史记录|之前的(?:消息|结果)")
_GLOBAL_DENIAL = re.compile(
    r"(?:不要|不用|无需|禁止|不许|别|不需要|不想|不允许|不).{0,8}(?:调用工具|使用工具|用工具|调用任何工具|使用任何工具|(?:查询|读取|获取)(?:任何|所有|全部)?(?:个人|校园)?(?:数据|记录|信息))|"
    r"(?:仅|只)(?:用文本回答|回答文本|解释|说明)(?:[，,。；;：:\s]|$)")
_GENERIC_DENIAL = re.compile(
    r"^\s*(?:请|先|暂时|现在|都|全部)*(?:(?:不要|不用|无需|别|禁止|不许|不必|不需要|不想|不允许|拒绝|不)"
    r"(?:再|继续)?(?:查询|查|读取|读|获取|调用|使用|执行|统计|看)(?:了|吧|这些|全部|所有|任何|个人|校园|数据|记录|信息|工具|操作|任务)*|"
    r"(?:取消|停止)(?:本次|这次|所有|全部|这些)?(?:查询|读取|操作|任务)?)(?:了|吧)?\s*$")
_QUOTED_BUILDING = re.compile(r'''(?:楼宇|building)\s*[:=：]\s*(?:"([^"\n]*)"|'([^'\n]*)'|“([^”\n]*)”|‘([^’\n]*)’)''', re.I)
_QUERY = re.compile(r"查询|查看|查|看看|显示|统计|列出|获取|汇总|对比|看")
_COMMAND_HELPERS = re.compile("|".join(sorted((
    "我的", "请你", "请", "帮我", "麻烦你", "麻烦", "现在", "顺便", "同时", "并且", "并", "再", "给我",
    "我要", "想要", "我想", "我需要", "能否", "能不能", "可以", "能", "只", "也", "一下", "谢谢", "吧", "吗",
    "和", "以及", "及", "与", "、", "一并", "的", "都", "分别", "然后", "还有"), key=len, reverse=True)))


def _command_shape(clause: str) -> bool:
    """A read verb alone grants nothing: its entire command body must fit.

    This is intentionally a small command language, not an interpretation of
    arbitrary prose. Unrecognized informational tails fail closed.
    """
    remainder = clause
    if any(term in clause for term in SERVICE_TERMS["classrooms"]):
        remainder = re.sub(r"(?:building|楼宇)\s*[:=：]\s*(?:__campus_building_\d+__|教学楼\s*[A-Za-z]+[0-9]*|实验楼|[A-Za-z][A-Za-z0-9_-]*)", "", remainder, flags=re.I)
        remainder = re.sub(r"min_seats\s*[:=：]\s*[^\s，,；;]+", "", remainder, flags=re.I)
        remainder = re.sub(r"教学楼\s*[A-Za-z]+[0-9]*|实验楼", "", remainder)
        number = r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
        remainder = re.sub(r"(?:至少|最少|不少于)\s*" + number + r"\s*(?:个?座(?:位)?|人)?|" + number + r"\s*个?座(?:位)?(?:以上|起)?", "", remainder)
    for term in sorted((term for terms in SERVICE_TERMS.values() for term in terms), key=len, reverse=True):
        remainder = remainder.replace(term, "")
    remainder = _COMMAND_HELPERS.sub("", _QUERY.sub("", remainder))
    return not remainder.strip()


def _implicit_query(clause: str) -> bool:
    # A bare noun request or "我的成绩和课表" is common. A narrative that only
    # mentions those nouns is not an instruction to read personal records.
    remainder = clause
    for terms in SERVICE_TERMS.values():
        for term in sorted(terms, key=len, reverse=True):
            remainder = remainder.replace(term, "")
    return not re.sub(r"我的|请|帮我|和|及|与|、|一并|也|一下|谢谢|吧|吗|\s", "", remainder)


def _classroom_arguments(question: str, literals=None) -> dict:
    building = re.search(r"(教学楼\s*[A-Za-z]+[0-9]*|实验楼)", question)
    # Preserved quoted values are atoms, even when Chinese objects or a seat
    # filter follow immediately. Never let free-text parsing absorb that suffix.
    explicit = re.search(r"(?:楼宇|building)\s*[:=：]\s*(__campus_building_\d+__)", question, re.I)
    if explicit is None:
        explicit = re.search(r'(?:楼宇|building)\s*[:=：]\s*["“]?([^"”\n，,；;]+?)(?=\s+(?:min_seats|building|楼宇)\s*[:=：]|["”\n，,；;]|$)', question, re.I)
    building_value = explicit.group(1).strip() if explicit else (building.group(1) if building else None)
    if literals and building_value in literals:
        building_value = literals[building_value]
    named_seats = re.search(r"min_seats\s*[:=：]\s*([^\s,，;；。]+)", question, re.I)
    seats = re.search(r"(?:至少|最少|不少于)\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*(?:个?座(?:位)?|人)?", question, re.I)
    if seats is None:
        seats = re.search(r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*个?座(?:位)?(?:以上|起)?", question)
    min_seats = 0
    if named_seats or seats:
        number = (named_seats or seats).group(1)
        try:
            min_seats = int(number) if re.fullmatch(r"[+-]?\d+", number) else number
        except ValueError:
            min_seats = number
    elif re.search(r"至少|最少|不少于|min_seats", question, re.I):
        min_seats = "invalid"
    return {"building": building_value, "min_seats": min_seats}


def select_service_calls(question: str) -> list[dict]:
    """Select explicit reads, in mention order, without consulting other context.

    Quoted/code text and explanatory clauses are data, never authorization. A
    clause denial applies to all its objects; separate positive clauses may grant
    other reads. Invalid current-request filters are preserved for preflight.
    """
    if not isinstance(question, str):
        return []
    if re.match(r"\s*(?:附件|历史消息|历史记录|工具结果|之前的结果|项目文档|项目文件)\s*[:：]", question):
        return []
    # Explicit parameter literals survive as inert placeholders. They can narrow
    # an already authorized classroom read but never contribute service names,
    # query verbs, denials or other control text to the authority selector.
    literals = {}
    def preserve_building(match):
        placeholder = f"__campus_building_{len(literals)}__"
        literals[placeholder] = next(value for value in match.groups() if value is not None)
        return "building=" + placeholder
    masked = _QUOTED_BUILDING.sub(preserve_building, question)
    text = re.sub(r"```[\s\S]*?```|`[^`]*`|[‘“\"](?:[^’”\"]*)[’”\"]|'[^']*'", "", masked)
    if _GLOBAL_DENIAL.search(text):
        return []
    text = re.sub(r"(?:但是|不过|然而|但)|(?:和|并且|以及|及)(?=(?:不要|不用|无需|别|禁止|不许|不必|不需要|不查))", "，", text)
    clauses = re.split(r"[，,。；;！!？?\n]", text)
    filter_text = "，".join(clause for clause in clauses if not _DENIAL.search(clause) and not _EXPLANATION.search(clause))
    selected = []
    denied = set()
    explanatory = False
    for clause in clauses:
        if not clause.strip():
            continue
        if _GENERIC_DENIAL.fullmatch(clause):
            return []
        if _DENIAL.search(clause):
            denied.update(name for name, terms in SERVICE_TERMS.items() if any(term in clause for term in terms))
            continue
        if _EXPLANATION.search(clause):
            explanatory = True
            continue
        explicit_query = bool(_QUERY.search(clause) and _command_shape(clause))
        if not explicit_query and (explanatory or not _implicit_query(clause)):
            continue
        mentions = []
        for name, terms in SERVICE_TERMS.items():
            positions = [clause.find(term) for term in terms if term in clause]
            if positions:
                mentions.append((min(positions), name))
        for _, name in sorted(mentions):
            if any(call["name"] == name for call in selected):
                continue
            arguments = _classroom_arguments(filter_text, literals) if name == "classrooms" else {}
            selected.append({"name": name, "arguments": arguments})
    return [call for call in selected if call["name"] not in denied]


def _utf8_string(value) -> bool:
    if type(value) is not str:
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


def valid_service_call(call) -> bool:
    """Structural built-in allowlist validation, with strict parameter bounds."""
    if type(call) is not dict or set(call) != {"name", "arguments"}:
        return False
    name, arguments = call["name"], call["arguments"]
    if type(name) is not str or name not in SERVICE_TERMS or type(arguments) is not dict:
        return False
    if name != "classrooms":
        return not arguments
    if not set(arguments) <= {"building", "min_seats"}:
        return False
    building, seats = arguments.get("building"), arguments.get("min_seats", 0)
    return ((building is None or (_utf8_string(building) and len(building) <= 120))
            and type(seats) is int and 0 <= seats <= 1000)


def _canonical(call: dict) -> tuple:
    arguments = call["arguments"]
    return ((call["name"], arguments.get("building"), arguments.get("min_seats", 0))
            if call["name"] == "classrooms" else (call["name"],))


class ReadTaskControl:
    """Cooperative checkpoints; synchronous in-flight reads are never killed."""
    def __init__(self, limit_seconds=20, clock=monotonic):
        # A caller may tighten the deadline but cannot expand the fixed budget.
        self._clock = clock
        self._deadline = clock() + min(20, max(0, limit_seconds))
        self._cancelled = Event()

    def cancel(self):
        self._cancelled.set()

    def checkpoint_reason(self):
        if self._cancelled.is_set():
            return "cancelled"
        if self._clock() >= self._deadline:
            return "deadline"
        return None


def _scalar(value) -> str:
    if type(value) is str and _utf8_string(value):
        # Provider strings are values, not sections or executable formatting.
        return value.replace("\r", " ").replace("\n", " ").replace("\x00", " ")
    if type(value) is bool:
        return "是" if value else "否"
    if type(value) is int:
        return str(value)
    if type(value) is float and math.isfinite(value):
        return str(value)
    raise ValueError("invalid_result")


def _format_result(name: str, raw, max_chars: int) -> dict:
    if type(raw) is not dict or type(raw.get("demo")) is not bool:
        raise ValueError("invalid_result")
    demo = raw["demo"]
    provenance = "演示数据，尚未连接学校系统" if demo else "学校接口数据"
    text = f"{LABELS[name]}（{provenance}）\n"
    truncated = False
    # Keep only a bounded public string, never the provider object or raw JSON.
    def append(line):
        nonlocal text, truncated
        remaining = max_chars - len(text)
        if len(line) > remaining:
            text += line[:max(0, remaining)]
            truncated = True
            return False
        text += line
        return True
    if name == "credits":
        if any(type(raw.get(key)) not in (int, float) or not math.isfinite(raw[key]) or raw[key] < 0
               for key in ("earned", "required")):
            raise ValueError("invalid_result")
        append(f"已获 {_scalar(raw['earned'])} 学分，培养方案要求 {_scalar(raw['required'])} 学分。")
    else:
        items = raw.get("items")
        if type(items) is not list:
            raise ValueError("invalid_result")
        if not items:
            append("当前筛选条件下没有记录。")
        for index, row in enumerate(items):
            if type(row) is not dict or any(key not in row for key in REQUIRED[name]):
                raise ValueError("invalid_result")
            values = []
            for field in FIELDS[name]:
                if field in row:
                    rendered = _scalar(row[field])
                    if field != "available":
                        values.append(f"{field}: {rendered}")
            if not append(("\n" if index else "") + " · ".join(values)):
                break
    if truncated:
        marker = "\n（结果已截断）"
        text = text[:max(0, max_chars - len(marker))] + marker[:max_chars]
    return {"ok": True, "demo": demo, "text": text, "truncated": truncated}


def run_read_task(question, calls, execute, control=None, trace=None) -> dict:
    """Preflight the entire plan, then dispatch independent reads at most once."""
    control = control if control is not None else ReadTaskControl()
    task = {"kind": "campus_reads", "limit_steps": LIMIT_STEPS, "planned_steps": 0,
            "attempted_steps": 0, "completed_steps": 0, "limit_ms": LIMIT_MS,
            "stop_reason": "completed", "truncated_results": 0}
    tool_calls, sections, successful_modes = [], [], []

    def finish(reason=None):
        if reason:
            task["stop_reason"] = reason
        notices = {"step_limit": "一次最多查询三项校园数据，请缩小查询范围。",
                   "invalid_request": "查询请求或参数无效，请明确要查询的校园数据和筛选条件。",
                   "cancelled": "查询已取消，以下保留已完成的结果。",
                   "deadline": "已到达查询时间检查点，以下保留已完成的结果。",
                   "tool_error": "部分查询未成功，请查看各项结果。"}
        answer = "\n\n".join(sections)
        if task["stop_reason"] in notices:
            answer = notices[task["stop_reason"]] + ("\n\n" + answer if answer else "")
        return {"answer": answer, "mode": "demo" if successful_modes and all(successful_modes) else "service",
                "tool_calls": tool_calls, "task": dict(task)}

    permitted = select_service_calls(question)
    if type(calls) not in (list, tuple) or not calls:
        return finish("invalid_request")
    # Snapshot plain, validated scalar arguments before any external callback.
    planned, seen = [], set()
    for call in calls:
        if not valid_service_call(call):
            return finish("invalid_request")
        key = _canonical(call)
        if key not in seen:
            seen.add(key)
            arguments = dict(call["arguments"])
            if call["name"] == "classrooms":
                arguments = {"building": arguments.get("building"), "min_seats": arguments.get("min_seats", 0)}
            planned.append({"name": call["name"], "arguments": arguments})
    task["planned_steps"] = min(4, len(planned))
    if any(not valid_service_call(call) for call in permitted):
        return finish("invalid_request")
    allowed = {_canonical(call) for call in permitted}
    if any(_canonical(call) not in allowed for call in planned):
        return finish("invalid_request")
    if len(permitted) > LIMIT_STEPS or len(planned) > LIMIT_STEPS:
        task["planned_steps"] = min(4, max(len(permitted), len(planned)))
        return finish("step_limit")
    retained_chars = 0
    had_failure = False
    for call in planned:
        stopped = control.checkpoint_reason()
        if stopped:
            return finish(stopped)
        task["attempted_steps"] += 1
        context = trace.phase("tool") if trace is not None else nullcontext(None)
        with context as step:
            try:
                raw = execute(call["name"], dict(call["arguments"]))
            except Exception:
                public = {"ok": False, "code": "tool_error"}
            else:
                try:
                    public = _format_result(call["name"], raw, min(RESULT_CHARS, TOTAL_CHARS - retained_chars))
                except Exception:
                    public = {"ok": False, "code": "invalid_result"}
            if not public["ok"]:
                if step is not None:
                    step["status"] = "failed"
                had_failure = True
            else:
                task["completed_steps"] += 1
                task["truncated_results"] += int(public["truncated"])
                retained_chars += len(public["text"])
                successful_modes.append(public["demo"])
        tool_calls.append({**call, "result": public})
        failure_text = "接口返回格式无效，未使用演示数据替代。" if public.get("code") == "invalid_result" else "查询未成功，未使用演示数据替代。"
        sections.append(public["text"] if public["ok"] else f"{LABELS[call['name']]}：{failure_text}")
        # Preserve completed evidence even when this synchronous read ran past
        # the checkpoint budget or cancellation arrived while it was in flight.
        stopped = control.checkpoint_reason()
        if stopped:
            return finish(stopped)
    return finish("tool_error" if had_failure else "completed")
