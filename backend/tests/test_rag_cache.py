"""Offline retrieval regressions: no application configuration, models or network."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields, is_dataclass
import hashlib
import importlib.util
from pathlib import Path
import sys
from threading import Barrier, Event
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


APP = Path(__file__).resolve().parents[1] / "app"


def module(name, **values):
    result = ModuleType(name)
    result.__dict__.update(values)
    return result


def load(name):
    full_name = "_campus_rag_cache_test." + name
    spec = importlib.util.spec_from_file_location(full_name, APP / (name + ".py"))
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


stubs = {
    "_campus_rag_cache_test": module("_campus_rag_cache_test", __path__=[str(APP)]),
    "_campus_rag_cache_test.config": module("_campus_rag_cache_test.config", get_settings=lambda: SimpleNamespace(enable_rag=False)),
    "_campus_rag_cache_test.models": module("_campus_rag_cache_test.models", Document=object),
    "sqlalchemy": module("sqlalchemy", select=lambda model: model),
    "sqlalchemy.orm": module("sqlalchemy.orm", Session=object),
}
with patch.dict(sys.modules, stubs):
    compiled_documents = load("compiled_documents")
    rag = load("rag")


def document(doc_id="a", title="Policy", content="alpha beta"):
    return SimpleNamespace(id=doc_id, title=title, content=content, updated_at="unchanged")


class Database:
    def __init__(self, docs):
        self.docs = docs
        self.reads = 0

    def scalars(self, _):
        self.reads += 1
        return SimpleNamespace(all=lambda: self.docs)


class RetrievalCacheTests(unittest.TestCase):
    def test_warm_search_reuses_compilation_but_reads_and_hashes_current_rows(self):
        index = rag.KnowledgeIndex()
        db = Database([document(), document("b", "Second", "alpha gamma")])
        expected = [{"title": "Policy", "snippet": "alpha beta"},
                    {"title": "Second", "snippet": "alpha gamma"}]
        self.assertEqual(index.search(db, "alpha"), expected)
        # The cache must eliminate real compilation, rather than caching results.
        with patch.object(compiled_documents, "chunks", side_effect=AssertionError("re-chunked")), \
                patch.object(compiled_documents, "terms", side_effect=AssertionError("re-tokenized")), \
                patch.object(index, "_version", wraps=index._version) as version:
            self.assertEqual(index.search(db, "beta"), expected[:1])
            self.assertEqual(version.call_count, 2)
        self.assertEqual(db.reads, 2)

    def test_sql_updates_titles_deletes_and_same_id_restore_are_authoritative(self):
        index = rag.KnowledgeIndex()
        db = Database([document()])
        self.assertEqual(index.search(db, "alpha")[0]["snippet"], "alpha beta")
        db.docs[0].content = "restored delta"
        self.assertEqual(index.search(db, "alpha"), [])
        self.assertEqual(index.search(db, "delta"), [{"title": "Policy", "snippet": "restored delta"}])
        db.docs[0].title = "renamed"
        self.assertEqual(index.search(db, "renamed"), [{"title": "renamed", "snippet": "restored delta"}])
        db.docs.clear()
        self.assertEqual(index.search(db, "delta"), [])
        self.assertEqual(index._compiled.info().entries, 0)
        # A different database/backup may reuse ids and timestamps.
        self.assertEqual(index.search(Database([document(content="fresh epsilon")]), "epsilon"),
                         [{"title": "Policy", "snippet": "fresh epsilon"}])

    def test_moving_nul_between_title_and_content_invalidates_same_id_cache(self):
        index = rag.KnowledgeIndex()
        doc = document(title="Alpha\0Beta", content="Gamma")
        db = Database([doc])
        self.assertEqual(index.search(db, "gamma"), [{"title": "Alpha\0Beta", "snippet": "Gamma"}])
        old_version = index._version(doc)
        doc.title, doc.content = "Alpha", "Beta\0Gamma"
        self.assertEqual(index.search(db, "gamma"), [{"title": "Alpha", "snippet": "Beta\0Gamma"}])
        self.assertNotEqual(index._version(doc), old_version)

    def test_ambiguous_legacy_vector_hash_is_rejected_in_favor_of_current_sql(self):
        index = rag.KnowledgeIndex()
        doc = document(title="Alpha", content="Beta\0Gamma")
        # This is also the old encoding for title='Alpha\0Beta', content='Gamma'.
        legacy_version = hashlib.sha256(b"Alpha\0Beta\0Gamma").hexdigest()
        result = {"metadatas": [[{"document_id": "a", "version": legacy_version}]],
                  "documents": [["Gamma"]]}
        collection = SimpleNamespace(count=lambda: 1, query=lambda **kwargs: result)
        index._embedder = SimpleNamespace(encode=lambda texts: {"dense_vecs": SimpleNamespace(tolist=lambda: [[1.0]])})
        with patch.object(index, "_vector", return_value=collection):
            self.assertEqual(index.search(Database([doc]), "gamma", 1),
                             [{"title": "Alpha", "snippet": "Beta\0Gamma"}])
        self.assertFalse(index.last_error)

    def test_stable_ranking_snippets_dedup_and_nonpositive_limit(self):
        index = rag.KnowledgeIndex()
        text = "alpha " + "x" * 644 + " beta tail"
        db = Database([document("a", "One", "alpha beta"), document("b", "Two", "alpha beta"),
                       document("c", "One", "alpha beta"), document("d", "Long", text)])
        expected = [{"title": "One", "snippet": "alpha beta"},
                    {"title": "Two", "snippet": "alpha beta"},
                    {"title": "Long", "snippet": "alpha " + "x" * 644}]
        self.assertEqual(index.search(db, "alpha", 3), expected)
        self.assertEqual(index.search(db, "alpha", 3), expected)
        self.assertEqual(index.search(db, "alpha", 0), [])
        self.assertEqual(db.reads, 2)

    def test_vector_validation_hashes_once_per_doc_and_keeps_current_fallback(self):
        index = rag.KnowledgeIndex()
        doc = document(content="alpha current")
        version = index._version(doc)
        result = {"metadatas": [[{"document_id": "a", "version": version}] * 4
                                 + [{"document_id": "deleted", "version": version}]],
                  "documents": [["first", "second", "third", "fourth", "deleted"]]}
        collection = SimpleNamespace(count=lambda: 5, query=lambda **kwargs: result)
        index._embedder = SimpleNamespace(encode=lambda texts: {"dense_vecs": SimpleNamespace(tolist=lambda: [[1.0]])})
        with patch.object(index, "_vector", return_value=collection), \
                patch.object(index, "_version", wraps=index._version) as hashed:
            self.assertEqual(index.search(Database([doc]), "alpha", 4),
                             [{"title": "Policy", "snippet": part} for part in ("first", "second", "third", "fourth")])
            self.assertEqual(hashed.call_count, 1)
            doc.content = "new beta"
            hashed.reset_mock()
            self.assertEqual(index.search(Database([doc]), "beta"), [{"title": "Policy", "snippet": "new beta"}])
            self.assertEqual(hashed.call_count, 1)
        with patch.object(index, "_vector", side_effect=RuntimeError("offline")):
            self.assertEqual(index.search(Database([doc]), "beta"), [{"title": "Policy", "snippet": "new beta"}])
        self.assertTrue(index.last_error)

    def test_satisfied_vector_results_only_hash_unique_matched_docs_in_large_corpus(self):
        docs = [document(f"doc-{number}", f"Policy {number}", "unmatched large body " * 4096)
                for number in range(100)]
        for matched_ids in (("doc-0",) * 4, ("doc-0", "doc-1", "doc-0", "doc-1")):
            with self.subTest(matched_ids=matched_ids):
                index = rag.KnowledgeIndex()
                versions = {doc.id: index._version(doc) for doc in docs[:2]}
                result = {"metadatas": [[{"document_id": doc_id, "version": versions[doc_id]}
                                         for doc_id in matched_ids]],
                          "documents": [[f"match-{number}" for number in range(4)]]}
                collection = SimpleNamespace(count=lambda: 4, query=lambda **kwargs: result)
                index._embedder = SimpleNamespace(encode=lambda texts: {"dense_vecs": SimpleNamespace(tolist=lambda: [[1.0]])})
                with patch.object(index, "_vector", return_value=collection), \
                        patch.object(index, "_version", wraps=index._version) as hashed:
                    self.assertEqual(index.search(Database(docs), "alpha", 4),
                                     [{"title": f"Policy {doc_id[-1]}", "snippet": f"match-{number}"}
                                      for number, doc_id in enumerate(matched_ids)])
                    self.assertEqual(hashed.call_count, len(set(matched_ids)))
                    self.assertEqual({call.args[0].id for call in hashed.call_args_list}, set(matched_ids))
                self.assertEqual(index._compiled.info().compiles, 0)


class CompiledDocumentCacheTests(unittest.TestCase):
    def test_byte_and_entry_caps_keep_stable_entries_without_changing_uncached_results(self):
        first = compiled_documents.compile_document("a", "v1", "Policy", "alpha beta")
        for budget, count in ((first.retained_bytes, 10), (10**6, 1)):
            with self.subTest(budget=budget, count=count):
                cache = compiled_documents.CompiledDocumentCache(budget, count)
                held = cache.get("a", "v1", "Policy", "alpha beta")
                for _ in range(3):
                    other = cache.get("b", "v2", "Policy", "beta gamma")
                    self.assertEqual(other.passages, (("beta gamma", frozenset({"policy", "beta", "gamma"})),))
                    self.assertIs(cache.get("a", "v1", "Policy", "alpha beta"), held)
                self.assertLessEqual(cache.info().retained_bytes, budget)
                self.assertEqual(cache.info().entries, 1)
                self.assertEqual(cache.info().hits, 3)
                self.assertEqual(cache.info().compiles, 4)

    def test_oversized_and_disabled_cache_still_search_and_replace_stale_version(self):
        for kwargs in ({"max_bytes": 1}, {"max_entries": 0}):
            index = rag.KnowledgeIndex()
            index._compiled = compiled_documents.CompiledDocumentCache(**kwargs)
            for _ in range(2):
                self.assertEqual(index.search(Database([document()]), "alpha"),
                                 [{"title": "Policy", "snippet": "alpha beta"}])
            self.assertEqual(index._compiled.info().entries, 0)
            self.assertEqual(index._compiled.info().retained_bytes, 0)
        cache = compiled_documents.CompiledDocumentCache(3000)
        old = cache.get("same", "old", "Policy", "alpha")
        new = cache.get("same", "new", "Policy", "beta " * 1000)
        self.assertNotEqual(old.version, new.version)
        self.assertEqual(cache.info().entries, 0)
        self.assertEqual(cache.info().retained_bytes, 0)
        self.assertEqual(old.passages, (("alpha", frozenset({"policy", "alpha"})),))

    def test_entry_weights_cover_retained_object_graph_and_pool_only_within_entry(self):
        cache = compiled_documents.CompiledDocumentCache()
        entry = cache.get("a", "version", "Policy", "repeatedtoken " * 200)
        other = cache.get("b", "version", "Policy", "repeatedtoken " * 200)
        tokens = [next(token for token in token_set if token == "repeatedtoken") for _, token_set in entry.passages]
        self.assertGreater(len(tokens), 1)
        self.assertTrue(all(token is tokens[0] for token in tokens))
        self.assertIsNot(tokens[0], next(token for token in other.passages[0][1] if token == "repeatedtoken"))
        seen = set()

        def retained_size(value):
            if id(value) in seen:
                return 0
            seen.add(id(value))
            size = sys.getsizeof(value)
            if isinstance(value, dict):
                return size + sum(retained_size(key) + retained_size(item) for key, item in value.items())
            if isinstance(value, (tuple, frozenset)):
                return size + sum(retained_size(item) for item in value)
            if is_dataclass(value):
                return size + sum(retained_size(getattr(value, field.name)) for field in fields(value))
            return size

        self.assertGreaterEqual(cache.info().retained_bytes, retained_size(cache._entries))
        with self.assertRaises(AttributeError):
            entry.title = "mutable"
        with self.assertRaises(AttributeError):
            entry.passages[0][1].add("mutable")

    def test_concurrent_compiles_return_their_own_version_snapshots(self):
        cache = compiled_documents.CompiledDocumentCache()
        barrier = Barrier(8)
        original = compiled_documents.compile_document

        def synchronized(*args):
            barrier.wait(timeout=5)
            return original(*args)

        def compile_version(number):
            entry = cache.get("same", str(number), "Policy", f"alpha version{number}")
            return entry.version, entry.passages[0][0]

        with patch.object(compiled_documents, "compile_document", side_effect=synchronized), \
                ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(compile_version, range(8)))
        self.assertEqual(results, [(str(number), f"alpha version{number}") for number in range(8)])
        self.assertEqual(cache.info().entries, 1)
        self.assertLessEqual(cache.info().retained_bytes, cache.max_bytes)

    def test_slow_old_compile_cannot_change_new_readers_immutable_result(self):
        cache = compiled_documents.CompiledDocumentCache()
        started, release = Event(), Event()
        original = compiled_documents.compile_document

        def delayed(doc_id, version, title, content):
            if version == "old":
                started.set()
                if not release.wait(timeout=5):
                    raise AssertionError("compiler held the cache lock")
            return original(doc_id, version, title, content)

        with patch.object(compiled_documents, "compile_document", side_effect=delayed), \
                ThreadPoolExecutor(max_workers=2) as executor:
            old = executor.submit(cache.get, "same", "old", "Old", "alpha old")
            self.assertTrue(started.wait(timeout=5))
            try:
                new = executor.submit(cache.get, "same", "new", "New", "alpha new").result(timeout=2)
            finally:
                release.set()
            self.assertEqual(old.result(timeout=2).passages[0][0], "alpha old")
        self.assertEqual(new.title, "New")
        self.assertEqual(new.passages[0][0], "alpha new")
        self.assertEqual(cache.get("same", "new", "New", "alpha new"), new)

    def test_chunks_public_contract_keeps_whitespace_overlap_and_validation(self):
        self.assertEqual(rag.chunks(" a\n b\t c ", 3, 1), ["a b", "b c", "c"])
        self.assertEqual(rag.chunks(" \n\t "), [])
        for size, overlap in ((0, 0), (1, -1), (1, 1), (2, 3)):
            with self.subTest(size=size, overlap=overlap), self.assertRaises(ValueError):
                rag.chunks("text", size, overlap)


if __name__ == "__main__":
    unittest.main()
