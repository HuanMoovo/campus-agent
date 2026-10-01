"""Run without installed web/AI dependencies: python -m unittest discover -s tests -p test_core_unit.py.

Only framework imports are substituted. These tests exercise the production egress,
parameter, and retrieval logic; request-model validation stays in test_api.py.
"""
import importlib.util
import math
from pathlib import Path
import socket
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


APP = Path(__file__).resolve().parents[1] / "app"


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code


def module(name, **values):
    result = ModuleType(name)
    result.__dict__.update(values)
    return result


settings = SimpleNamespace(allowed_plugin_hosts={"plugins.example.edu"}, enable_rag=True)
stubs = {
    "_campus_core_test": module("_campus_core_test", __path__=[str(APP)]),
    "_campus_core_test.config": module("_campus_core_test.config", BASE_DIR=APP.parent, get_settings=lambda: settings),
    "_campus_core_test.models": module("_campus_core_test.models", Plugin=object, Document=object),
    "pydantic": module("pydantic", BaseModel=object, ConfigDict=dict, HttpUrl=str,
                       Field=lambda *args, **kwargs: None,
                       field_validator=lambda *args, **kwargs: lambda fn: fn,
                       model_validator=lambda *args, **kwargs: lambda fn: fn),
    "sqlalchemy": module("sqlalchemy", select=lambda model: model),
    "sqlalchemy.orm": module("sqlalchemy.orm", Session=object),
    "fastapi": module("fastapi", HTTPException=HTTPException),
    "httpx": module("httpx", HTTPError=type("HTTPError", (Exception,), {})),
}


def load(name):
    full_name = "_campus_core_test." + name
    spec = importlib.util.spec_from_file_location(full_name, APP / (name + ".py"))
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


with patch.dict(sys.modules, stubs):
    schemas = load("schemas")
    plugins = load("plugins")
    rag = load("rag")


def dns(address):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]


class PluginSecurityTests(unittest.TestCase):
    def test_private_and_mixed_dns_are_rejected(self):
        for addresses in (dns("127.0.0.1"), dns("169.254.169.254"), dns("8.8.8.8") + dns("10.0.0.1")):
            with self.subTest(addresses=addresses), patch.object(plugins.socket, "getaddrinfo", return_value=addresses):
                with self.assertRaises(HTTPException) as raised:
                    plugins.validate_plugin_url("https://plugins.example.edu/data")
                self.assertEqual(raised.exception.status_code, 400)

    def test_unsafe_urls_are_rejected_before_dns(self):
        for url in ("http://plugins.example.edu/data", "https://evil.example/data", "https://plugins.example.edu:8443/",
                    "https://user:pass@plugins.example.edu/", "https://plugins.example.edu/#fragment", "https://plugins.example.edu:invalid/"):
            with self.subTest(url=url), patch.object(plugins.socket, "getaddrinfo") as resolve:
                with self.assertRaises(HTTPException):
                    plugins.validate_plugin_url(url)
                resolve.assert_not_called()

    def request(self, response_body, status=200, limit=100):
        response = SimpleNamespace(status_code=status, raise_for_status=lambda: None,
                                   iter_bytes=lambda **kwargs: iter(response_body))
        stream_context = unittest.mock.MagicMock()
        stream_context.__enter__.return_value = response
        client = unittest.mock.MagicMock()
        client.stream.return_value = stream_context
        client_context = unittest.mock.MagicMock()
        client_context.__enter__.return_value = client
        factory = unittest.mock.Mock(return_value=client_context)
        with patch.object(plugins.socket, "getaddrinfo", return_value=dns("8.8.8.8")) as resolve, patch.object(plugins.httpx, "Client", factory, create=True):
            result = plugins.fetch_plugin_json("https://plugins.example.edu/data?fixed=1", max_bytes=limit)
        return result, factory, client, resolve

    def test_connection_is_pinned_and_tls_preserves_hostname(self):
        result, factory, client, resolve = self.request([b'{"ok":true}'])
        self.assertEqual(result, {"ok": True})
        resolve.assert_called_once()
        self.assertFalse(factory.call_args.kwargs["trust_env"])
        self.assertFalse(factory.call_args.kwargs["follow_redirects"])
        args, kwargs = client.stream.call_args
        self.assertEqual(args, ("GET", "https://8.8.8.8/data?fixed=1"))
        self.assertEqual(kwargs["headers"]["Host"], "plugins.example.edu")
        self.assertEqual(kwargs["extensions"]["sni_hostname"], "plugins.example.edu")

    def test_redirects_and_oversized_responses_are_rejected(self):
        for body, status, limit, expected in (([b"{}"], 302, 100, 502), ([b"123", b"456"], 200, 5, 413)):
            with self.subTest(status=status), self.assertRaises(HTTPException) as raised:
                self.request(body, status, limit)
            self.assertEqual(raised.exception.status_code, expected)

    def test_schema_and_parameter_constraints_are_enforced(self):
        schema = {"type": "object", "properties": {"seats": {"type": "integer", "minimum": 1, "maximum": 100},
                                                        "building": {"type": "string", "enum": ["A", "B"]}}, "required": ["seats"]}
        self.assertEqual(plugins.validate_plugin_parameters({"seats": 30}, schema), {"seats": 30})
        for params in ({}, {"seats": True}, {"seats": 101}, {"seats": 30, "unknown": "value"}, {"seats": 30, "building": "C"}):
            with self.subTest(params=params), self.assertRaises(HTTPException):
                plugins.validate_plugin_parameters(params, schema)
        for invalid in ({"properties": {"q": {"type": "object"}}}, {"required": ["missing"]}, {"additionalProperties": True}):
            with self.subTest(schema=invalid), self.assertRaises(ValueError):
                schemas.validate_parameter_schema(invalid)
        for value in (math.nan, math.inf, True, "2"):
            self.assertFalse(schemas.parameter_type_matches(value, "number"))


class Collection:
    def __init__(self):
        self.rows = {}

    def upsert(self, ids, embeddings, documents, metadatas):
        self.rows.update({key: (text, meta) for key, text, meta in zip(ids, documents, metadatas)})

    def get(self, where=None, **kwargs):
        rows = [(key, value) for key, value in self.rows.items() if where is None or value[1]["document_id"] == where["document_id"]]
        return {"ids": [row[0] for row in rows], "metadatas": [row[1][1] for row in rows]}

    def delete(self, ids=None, where=None):
        for key in (ids if ids is not None else self.get(where=where)["ids"]):
            self.rows.pop(key, None)

    def count(self):
        return len(self.rows)

    def query(self, query_embeddings, n_results):
        rows = list(self.rows.values())[:n_results]
        return {"documents": [[row[0] for row in rows]], "metadatas": [[row[1] for row in rows]]}


def database(docs):
    return SimpleNamespace(scalars=lambda query: SimpleNamespace(all=lambda: docs))


class KnowledgeConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.index = rag.KnowledgeIndex()
        self.index._collection = Collection()
        self.index._embedder = SimpleNamespace(encode=lambda texts: {"dense_vecs": SimpleNamespace(tolist=lambda: [[1.0]] * len(texts))})

    def test_replacement_removes_previous_chunks(self):
        document = SimpleNamespace(id="d1", title="规定", content="旧版奖学金申请流程" * 100)
        self.index.index(document)
        old_ids = set(self.index._collection.rows)
        document.content = "新版奖学金申请流程"
        self.index.index(document)
        self.assertFalse(old_ids & set(self.index._collection.rows))
        self.assertEqual(self.index.search(database([document]), "奖学金"), [{"title": "规定", "snippet": "新版奖学金申请流程"}])

    def test_failed_embedding_keeps_recoverable_old_index(self):
        document = SimpleNamespace(id="d1", title="规定", content="旧版申请流程")
        self.index.index(document)
        previous = dict(self.index._collection.rows)
        document.content = "新版申请流程"
        with patch.object(self.index._embedder, "encode", side_effect=RuntimeError("model unavailable")):
            with self.assertRaises(RuntimeError):
                self.index.index(document)
        self.assertEqual(self.index._collection.rows, previous)
        self.assertEqual(self.index.search(database([document]), "申请")[0]["snippet"], document.content)

    def test_deleted_and_stale_documents_never_leak_into_search(self):
        document = SimpleNamespace(id="d1", title="规定", content="旧版申请流程")
        self.index.index(document)
        self.assertEqual(self.index.search(database([]), "申请"), [])
        document.content = "更新后的奖学金办理流程"
        result = self.index.search(database([document]), "奖学金")
        self.assertEqual(result[0]["snippet"], document.content)
        self.assertNotIn("旧版", str(result))

    def test_unavailable_vector_model_falls_back_to_current_text(self):
        document = SimpleNamespace(id="d1", title="奖学金", content="奖学金申请需要成绩证明")
        with patch.object(self.index, "_vector", side_effect=RuntimeError("model missing")):
            self.assertEqual(self.index.search(database([document]), "奖学金")[0]["snippet"], document.content)
        self.assertTrue(self.index.last_error)

    def test_rebuild_removes_orphans_and_preserves_current_documents(self):
        orphan = SimpleNamespace(id="deleted", title="删除", content="过期资料")
        current = SimpleNamespace(id="current", title="保留", content="最新资料")
        self.index.index(orphan)
        self.assertEqual(self.index.rebuild(database([current])), 1)
        self.assertEqual({meta["document_id"] for _, meta in self.index._collection.rows.values()}, {"current"})
        self.assertEqual(self.index.search(database([current]), "资料", limit=0), [])


if __name__ == "__main__":
    unittest.main()
