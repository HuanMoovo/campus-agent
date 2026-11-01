"""Bound MCP exposure to the current request and validate calls before launch."""
from __future__ import annotations

import json
import re

from jsonschema import Draft202012Validator
from jsonschema.validators import validator_for
from referencing import Registry, Resource
from referencing.jsonschema import specification_with


MAX_SELECTED_TOOLS = 4
MAX_TOOL_DEFINITION_CHARS = 12000
MAX_ARGUMENT_CHARS = 8192

_FUNCTION_NAME = re.compile(r"mcp__[A-Za-z0-9_-]{1,59}\Z")
_CLAUSE_BREAK = re.compile(r"[，,。；;！？!?\n]")
_DENIAL = re.compile(
    r"不要|不必|不用|不能|不应|不允许|不(?:调用|使用|执行|运行)|无需|禁止|请勿|勿|别(?:再|去)?(?:调用|使用|执行|运行|用)|"
    r"\b(?:do\s+not|don['’]t|never|without|avoid|must\s+not)\b", re.IGNORECASE)
_EXPLANATION = re.compile(
    r"是什么|什么(?:意思|作用|功能)|怎么用|如何使用|介绍|解释|讲解|说明(?:一下)?|文档|"
    r"\b(?:what\s+is|explain|describe|documentation|how\s+to\s+use)\b", re.IGNORECASE)
_INVOCATION = re.compile(r"调用|使用|执行|运行|改用|\b(?:call|use|run|invoke|execute)\b", re.IGNORECASE)
_GLOBAL_DENIAL = re.compile(
    r"(?:不要|不必|不用|不能|禁止|请勿|勿|别)\s*(?:调用|使用|执行|运行|用)?\s*"
    r"(?:任何|所有|全部)?\s*(?:外部|第三方|MCP)?\s*工具|"
    r"\b(?:do\s+not|don['’]t|never|must\s+not|without)\s+(?:call|use|run|invoke|execute)?\s*"
    r"(?:(?:any|all|external|MCP|the)\s+)*tools?\b", re.IGNORECASE)


def _json_text(value) -> str:
    """Reject Python-only values and non-finite numbers before schema evaluation."""
    pending = [value]
    visited = set()
    while pending:
        item = pending.pop()
        if isinstance(item, (dict, list)):
            if id(item) in visited:
                continue  # json.dumps rejects cycles; shared JSON subtrees are valid.
            visited.add(id(item))
            if isinstance(item, dict):
                if any(not isinstance(key, str) for key in item):
                    raise ValueError("JSON 对象的键必须是字符串")
                pending.extend(item.values())
            else:
                pending.extend(item)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise ValueError("参数必须是 JSON 数据")
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _schema_validator(schema: dict):
    if not isinstance(schema, dict):
        raise ValueError("工具参数定义必须是对象")
    _json_text(schema)
    validator_type = validator_for(schema, default=Draft202012Validator if "$schema" not in schema else None)
    if validator_type is None:
        raise ValueError("不支持的 JSON Schema 版本")
    validator_type.check_schema(schema)
    dialect = validator_type.META_SCHEMA.get("$id") or validator_type.META_SCHEMA["id"]
    resource = Resource.from_contents(schema, default_specification=specification_with(dialect.rstrip("#")))
    pending = [resource]
    while pending:
        current = pending.pop()
        if isinstance(current.contents, dict):
            for keyword in ("$ref", "$dynamicRef", "$recursiveRef"):
                reference = current.contents.get(keyword)
                if reference is not None and (not isinstance(reference, str) or (reference and not reference.startswith("#"))):
                    raise ValueError("工具参数定义不得引用外部资源")
            if "$schema" in current.contents and validator_for(current.contents, default=None) is None:
                raise ValueError("不支持的 JSON Schema 版本")
        pending.extend(current.subresources())
    # An explicit empty registry never retrieves resources over HTTP or from disk.
    return validator_type(schema, registry=Registry())


def select_mcp_entries(question: str, entries: list[dict]) -> list[dict]:
    """Select exact names in the request, conservatively excluding denials/docs.

    The caller supplies only the user's current request, never attachments or
    model output. Selection is capability scoping, not a natural-language parser.
    Definitions are kept intact and counted in their actual OpenAI tool wrapper.
    """
    if not isinstance(question, str):
        return []
    if _GLOBAL_DENIAL.search(question):
        return []
    clauses = _CLAUSE_BREAK.split(question)
    selected, definitions, seen = [], [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("function")
        if not isinstance(name, str) or not _FUNCTION_NAME.fullmatch(name) or name in seen:
            continue
        mention = re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(name) + r"(?![A-Za-z0-9_-])")
        matching = [clause for clause in clauses if mention.search(clause)]
        # A negated mention vetoes the same tool even if it is repeated elsewhere.
        if not matching or any(_DENIAL.search(clause) for clause in matching):
            continue
        # A dangling mention after a denial must not turn into permission when
        # punctuation splits the instruction. An explicit positive second action
        # can still request a different tool ("不要调用 X，改用 Y").
        if _DENIAL.search(question) and not any(_INVOCATION.search(clause) for clause in matching):
            continue
        if not any(not _EXPLANATION.search(clause) for clause in matching):
            continue
        definition = {"type": "function", "function": {
            "name": name, "description": entry.get("description", ""), "parameters": entry.get("inputSchema")}}
        try:
            candidate = [*definitions, definition]
            if len(_json_text(candidate)) > MAX_TOOL_DEFINITION_CHARS:
                continue
            _schema_validator(entry.get("inputSchema"))
        except Exception:
            # Tool metadata is untrusted; invalid schemas never reach the planner.
            continue
        selected.append(entry)
        definitions = candidate
        seen.add(name)
        if len(selected) == MAX_SELECTED_TOOLS:
            break
    return selected


def validate_arguments(schema: dict, arguments: dict) -> None:
    """Validate full inline JSON Schema with safe errors and no resource retrieval."""
    try:
        if not isinstance(arguments, dict) or len(_json_text(arguments)) > MAX_ARGUMENT_CHARS:
            raise ValueError("工具参数必须是有界 JSON 对象")
        validator = _schema_validator(schema)
        validator.validate(arguments)
    except Exception:
        # jsonschema diagnostics can contain argument values, schemas and URIs.
        raise ValueError("工具参数或参数定义无效，请检查必填项、类型、取值及大小；不支持外部引用。") from None
