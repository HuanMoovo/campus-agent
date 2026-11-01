"""Request-scoped MCP selection and validation, without model or remote calls."""
from copy import deepcopy
import importlib
import json
from types import SimpleNamespace

import pytest


def policy():
    return importlib.import_module("app.tool_policy")


def entry(name="mcp__campus__echo", *, description="回显", schema=None):
    return {"function": name, "server_id": "server-1", "server": "campus", "tool": "echo",
            "description": description, "inputSchema": schema or {
                "type": "object", "properties": {"text": {"type": "string"}},
                "required": ["text"], "additionalProperties": False}}


@pytest.mark.parametrize("question", [
    "你好", "查询课表", "调用 xmcp__campus__echo", "调用 mcp__campus__echo_extra",
    "调用 mcp__campus__echo-v2", "不要调用 mcp__campus__echo", "别使用 mcp__campus__echo",
    "请勿执行 mcp__campus__echo", "无需使用 mcp__campus__echo", "mcp__campus__echo 是什么？",
    "解释 mcp__campus__echo 的作用", "mcp__campus__echo 怎么用？",
    "Do not call mcp__campus__echo", "Don't use mcp__campus__echo",
    "What is mcp__campus__echo?", "Explain mcp__campus__echo",
])
def test_unrequested_negated_and_documentary_mentions_do_not_expose_tools(question):
    assert policy().select_mcp_entries(question, [entry()]) == []


@pytest.mark.parametrize("question", ["调用 mcp__campus__echo", "请使用`mcp__campus__echo`回显", "mcp__campus__echo", "Call mcp__campus__echo."])
def test_explicit_exact_name_selects_registered_tool_without_mutation(question):
    rows = [entry()]
    before = deepcopy(rows)
    selected = policy().select_mcp_entries(question, rows)
    assert [row["function"] for row in selected] == ["mcp__campus__echo"]
    assert rows == before


def test_one_negated_tool_does_not_authorize_it_beside_a_requested_tool():
    rows = [entry(), entry("mcp__campus__search")]
    selected = policy().select_mcp_entries("不要调用 mcp__campus__echo，改用 mcp__campus__search", rows)
    assert [row["function"] for row in selected] == ["mcp__campus__search"]


@pytest.mark.parametrize("question", [
    "不要调用任何工具，包括 mcp__campus__echo", "不要调用工具，包括调用 mcp__campus__echo",
    "禁止使用外部工具；比如 mcp__campus__echo", "不要调用，mcp__campus__echo",
    "Never call any tools, including mcp__campus__echo",
])
def test_global_or_inherited_denials_apply_across_clause_boundaries(question):
    assert policy().select_mcp_entries(question, [entry()]) == []


def test_selection_caps_count_and_deduplicates_catalog_entries():
    rows = [entry(f"mcp__campus__tool{i}") for i in range(6)]
    selected = policy().select_mcp_entries("调用 " + "、".join(row["function"] for row in rows), rows + rows)
    assert [row["function"] for row in selected] == [f"mcp__campus__tool{i}" for i in range(4)]


def test_oversize_definition_is_skipped_whole_without_dropping_constraints():
    schema = {"type": "object", "properties": {"text": {"enum": ["x" * 13000]}}}
    rows = [entry(schema=schema), entry("mcp__campus__small")]
    before = deepcopy(rows)
    selected = policy().select_mcp_entries("调用 mcp__campus__echo 和 mcp__campus__small", rows)
    assert [row["function"] for row in selected] == ["mcp__campus__small"]
    assert rows == before


def test_total_tool_definition_budget_includes_description_and_json_wrapper():
    rows = [entry(f"mcp__campus__tool{i}", description="长" * 5900) for i in range(3)]
    selected = policy().select_mcp_entries("调用 " + "、".join(row["function"] for row in rows), rows)
    assert len(selected) == 1
    from app.mcp_registry import openai_tools
    assert len(json.dumps(openai_tools(selected), ensure_ascii=False)) <= 12000


def test_selection_skips_invalid_and_external_schema_without_rewriting_it():
    rows = [entry(schema={"$ref": "https://private.invalid/schema"}),
            entry("mcp__campus__broken", schema={"type": "invalid"}),
            entry("mcp__campus__valid")]
    before = deepcopy(rows)
    selected = policy().select_mcp_entries("调用 " + "、".join(row["function"] for row in rows), rows)
    assert [row["function"] for row in selected] == ["mcp__campus__valid"]
    assert rows == before


@pytest.mark.parametrize("question", ["不调用 mcp__campus__echo", "不使用 mcp__campus__echo", "讲解 mcp__campus__echo 的功能"])
def test_short_negations_and_explanation_requests_do_not_select_a_tool(question):
    assert policy().select_mcp_entries(question, [entry()]) == []


@pytest.mark.parametrize("arguments", [
    {}, {"text": 123}, {"text": "secret-argument", "extra": True}, [], "text", None,
    {"text": "x" * 8192}, {"text": float("nan")}, {"text": float("inf")},
    {"text": [float("-inf")]}, {1: "non-string-key"},
])
def test_invalid_arguments_raise_safe_errors(arguments):
    with pytest.raises(ValueError) as error:
        policy().validate_arguments(entry()["inputSchema"], arguments)
    assert "secret-argument" not in str(error.value)
    assert str(error.value)


def test_complex_inline_schema_is_enforced_instead_of_ignored():
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"item": {"type": "object", "properties": {"count": {"type": "integer", "minimum": 1}},
                             "required": ["count"], "additionalProperties": False}},
        "type": "object", "properties": {"kind": {"enum": ["one", "many"]},
            "items": {"type": "array", "items": {"$ref": "#/$defs/item"}, "minItems": 1}},
        "required": ["kind", "items"], "additionalProperties": False,
        "if": {"properties": {"kind": {"const": "one"}}},
        "then": {"properties": {"items": {"maxItems": 1}}},
    }
    valid = {"kind": "one", "items": [{"count": 2}]}
    before = deepcopy((schema, valid))
    policy().validate_arguments(schema, valid)
    assert (schema, valid) == before
    for invalid in ({"kind": "one", "items": [{"count": True}]},
                    {"kind": "one", "items": [{"count": 0}]},
                    {"kind": "one", "items": [{"count": 1}, {"count": 2}]}):
        with pytest.raises(ValueError):
            policy().validate_arguments(schema, invalid)


def test_literal_ref_named_data_is_not_mistaken_for_a_schema_reference():
    schema = {"type": "object", "properties": {"payload": {"const": {"$ref": "literal-value"}}},
              "required": ["payload"]}
    policy().validate_arguments(schema, {"payload": {"$ref": "literal-value"}})


def test_supported_older_draft_and_oneof_are_enforced():
    schema = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object", "properties": {
        "value": {"oneOf": [{"type": "integer", "minimum": 3}, {"type": "string", "pattern": "^ok$"}]}},
        "required": ["value"]}
    policy().validate_arguments(schema, {"value": "ok"})
    policy().validate_arguments(schema, {"value": 4})
    with pytest.raises(ValueError):
        policy().validate_arguments(schema, {"value": "secret-argument"})


@pytest.mark.parametrize("schema", [
    {"$ref": "https://private.invalid/schema.json"}, {"$ref": "file:///private.json"},
    {"$ref": "relative.json"}, {"$dynamicRef": "https://private.invalid/schema"},
    {"$defs": {"unused": {"$ref": "https://private.invalid/schema"}}},
    {"type": "not-a-valid-type"}, {"$schema": "https://private.invalid/dialect"},
    {"properties": {"text": {"$ref": "#/$defs/missing"}}},
])
def test_external_references_and_invalid_schemas_fail_closed(schema, monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: pytest.fail("schema must never use network"))
    with pytest.raises(ValueError) as error:
        policy().validate_arguments(schema, {"text": "secret-argument"})
    assert "secret-argument" not in str(error.value)
    assert "private.invalid" not in str(error.value)


@pytest.fixture
def registry_boundary(monkeypatch):
    from app import mcp_registry
    rows = [entry()]
    server = SimpleNamespace(enabled=True, command="unused", args=[], env={})
    monkeypatch.setattr(mcp_registry, "catalog", lambda db, enabled_only=True: rows)
    launched = []

    class FakeProcess:
        def __init__(self, *args, **kwargs):
            launched.append(True)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def call_tool(self, name, arguments):
            return {"is_error": False, "text": "echo: " + str(arguments.get("text", ""))}

    monkeypatch.setattr(mcp_registry.mcp_client, "McpStdioClient", FakeProcess)
    return mcp_registry, SimpleNamespace(get=lambda *args: server), server, rows, launched


@pytest.mark.parametrize("arguments", [{}, {"text": 123}, {"text": "secret-argument", "extra": 1}, []])
def test_registry_rejects_invalid_arguments_before_process_start(registry_boundary, arguments):
    registry, db, server, rows, launched = registry_boundary
    result = registry.call(db, "mcp__campus__echo", arguments)
    assert result["ok"] is False
    assert "secret-argument" not in result["error"]
    assert launched == []


def test_registry_still_executes_valid_arguments(registry_boundary):
    registry, db, server, rows, launched = registry_boundary
    result = registry.call(db, "mcp__campus__echo", {"text": "hello"})
    assert result["ok"] is True
    assert result["text"] == "echo: hello"
    assert launched == [True]


def test_registry_rejects_bad_schema_before_process_start(registry_boundary):
    registry, db, server, rows, launched = registry_boundary
    rows[0]["inputSchema"] = {"$ref": "https://private.invalid/schema"}
    result = registry.call(db, "mcp__campus__echo", {"text": "hello"})
    assert result["ok"] is False
    assert "private.invalid" not in result["error"]
    assert launched == []


@pytest.mark.parametrize("schema", [False, "broken", None, []])
@pytest.mark.parametrize("discovered", [True, False])
def test_invalid_schema_survives_no_permissive_normalization(schema, discovered, monkeypatch):
    from app import mcp_client, mcp_registry
    original = [{"name": "broken", "description": "bad schema", "inputSchema": schema}]
    if discovered:
        connection = mcp_client.McpStdioClient(command="never-started")
        monkeypatch.setattr(connection, "_request", lambda *args: {"tools": original})
        cached = connection.list_tools()
    else:
        cached = original  # Also cover pre-existing cached invalid definitions.
    server = SimpleNamespace(id="one", name="campus", last_tools=cached, enabled=True,
                             command="never-started", args=[], env={})
    db = SimpleNamespace(scalars=lambda *args: SimpleNamespace(all=lambda: [server]), get=lambda *args: server)
    def unexpected_process(*args, **kwargs):
        pytest.fail("An invalid schema must never start the MCP process")
    monkeypatch.setattr(mcp_client, "McpStdioClient", unexpected_process)
    result = mcp_registry.call(db, "mcp__campus__broken", {"unexpected": "allowed"})
    assert result["ok"] is False


def test_unknown_and_disabled_tools_never_start_a_process(registry_boundary):
    registry, db, server, rows, launched = registry_boundary
    assert registry.call(db, "mcp__unknown__tool", {})["ok"] is False
    server.enabled = False
    assert registry.call(db, "mcp__campus__echo", {"text": "hello"})["ok"] is False
    assert launched == []
