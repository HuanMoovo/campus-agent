"""Bounded, immutable keyword preprocessing; no database or model dependencies.

Callers supply the version of their current SQL snapshot. Retained entries never
own ORM objects, and readers can safely keep an entry after it is replaced.
"""
from dataclasses import dataclass
import re
import sys
from threading import RLock

from .text_terms import terms


def chunks(text: str, size: int = 650, overlap: int = 90) -> list[str]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("Chunk size must be positive and overlap must be smaller than size")
    text = re.sub(r"\s+", " ", text).strip()
    return [text[i:i + size] for i in range(0, len(text), size - overlap)] if text else []


@dataclass(frozen=True, slots=True)
class CompiledDocument:
    version: str
    title: str
    passages: tuple[tuple[str, frozenset[str]], ...]
    retained_bytes: int


@dataclass(frozen=True, slots=True)
class CacheInfo:
    entries: int
    retained_bytes: int
    hits: int
    compiles: int


def compile_document(document_id: str, version: str, title: str, content: str) -> CompiledDocument:
    # Pool only within this entry. The temporary dictionary is not retained and
    # no process-wide intern table grows with user-supplied text.
    pool: dict[str, str] = {}
    passages = tuple((part, frozenset(pool.setdefault(token, token) for token in terms(title + " " + part)))
                     for part in chunks(content))
    # Count each retained pooled string once, every container, and id/version/
    # title strings. The allowance exceeds the entry object, integer accounting
    # and dictionary slot/key overhead (including resizing slack).
    weight = (512 + sys.getsizeof(document_id) + sys.getsizeof(version)
              + sys.getsizeof(title) + sys.getsizeof(passages))
    weight += sum(sys.getsizeof(row) + sys.getsizeof(row[0]) + sys.getsizeof(row[1]) for row in passages)
    weight += sum(sys.getsizeof(token) for token in pool.values())
    return CompiledDocument(version, title, passages, weight)


class CompiledDocumentCache:
    def __init__(self, max_bytes: int = 32 * 1024 * 1024, max_entries: int = 2048):
        self.max_bytes = max(0, max_bytes)
        self.max_entries = max(0, max_entries)
        self._entries: dict[str, CompiledDocument] = {}
        self._retained_bytes = 0
        self._hits = 0
        self._compiles = 0
        self._lock = RLock()

    def prune(self, live_ids: set[str]) -> None:
        with self._lock:
            if any(document_id not in live_ids for document_id in self._entries):
                # Rebuild to release deleted dictionary slots as well as entries.
                self._entries = {key: entry for key, entry in self._entries.items() if key in live_ids}
                self._retained_bytes = sum(entry.retained_bytes for entry in self._entries.values())

    def get(self, document_id: str, version: str, title: str, content: str) -> CompiledDocument:
        with self._lock:
            existing = self._entries.get(document_id)
            if existing is not None and existing.version == version:
                self._hits += 1
                return existing
        # Compilation and all model/network operations remain outside this lock.
        # The budget bounds retained entries, not SQL bodies or in-flight readers.
        entry = compile_document(document_id, version, title, content)
        with self._lock:
            self._compiles += 1
            existing = self._entries.get(document_id)
            if existing is not None and existing.version == version:
                return existing
            previous = self._entries.pop(document_id, None)
            if previous is not None:
                self._retained_bytes -= previous.retained_bytes
            # Stable first-fit admission prevents full-scan LRU eviction thrash
            # when the corpus exceeds the budget. Unfit entries still search.
            if (len(self._entries) < self.max_entries
                    and self._retained_bytes + entry.retained_bytes <= self.max_bytes):
                self._entries[document_id] = entry
                self._retained_bytes += entry.retained_bytes
        return entry

    def info(self) -> CacheInfo:
        with self._lock:
            return CacheInfo(len(self._entries), self._retained_bytes, self._hits, self._compiles)
