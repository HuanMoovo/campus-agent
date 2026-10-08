import re
import hashlib
import logging
from threading import RLock

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Document
from .text_terms import terms

logger = logging.getLogger(__name__)


def chunks(text: str, size: int = 650, overlap: int = 90) -> list[str]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("Chunk size must be positive and overlap must be smaller than size")
    text = re.sub(r"\s+", " ", text).strip()
    return [text[i:i + size] for i in range(0, len(text), size - overlap)] if text else []


class KnowledgeIndex:
    def __init__(self):
        self._collection = None
        self._embedder = None
        self._lock = RLock()
        self.last_error = False

    @staticmethod
    def _version(document: Document) -> str:
        return hashlib.sha256((document.title + "\0" + document.content).encode("utf-8")).hexdigest()

    def _vector(self):
        if not get_settings().enable_rag:
            return None
        if self._collection is None:
            import chromadb
            from FlagEmbedding import BGEM3FlagModel

            self._embedder = BGEM3FlagModel(get_settings().bge_model_name, use_fp16=False)
            self._collection = chromadb.PersistentClient(path=str(get_settings().data_dir / "chroma")).get_or_create_collection("campus_documents")
        return self._collection

    def index(self, document: Document):
        with self._lock:
            collection = self._vector()
            if collection is None:
                return
            parts = chunks(document.content)
            version = self._version(document)
            ids = [f"{document.id}:{version}:{i}" for i in range(len(parts))]
            # Produce and store the replacement before removing previous chunks.
            # If the embedder fails, the last successful index remains recoverable.
            if parts:
                vectors = self._embedder.encode(parts)["dense_vecs"].tolist()
                collection.upsert(ids=ids, embeddings=vectors, documents=parts,
                                  metadatas=[{"document_id": document.id, "title": document.title, "version": version} for _ in parts])
            existing = collection.get(where={"document_id": document.id})["ids"]
            stale = list(set(existing) - set(ids))
            if stale:
                collection.delete(ids=stale)

    def remove(self, document_id: str):
        with self._lock:
            collection = self._vector()
            if collection is not None:
                collection.delete(where={"document_id": document_id})

    def rebuild(self, db: Session) -> int:
        docs = db.scalars(select(Document)).all()
        with self._lock:
            collection = self._vector()
            if collection is not None:
                for doc in docs:
                    self.index(doc)
                # Only remove orphan chunks after current documents have indexed.
                current_ids = {doc.id for doc in docs}
                existing = collection.get(include=["metadatas"])
                orphan_ids = [item_id for item_id, meta in zip(existing["ids"], existing["metadatas"])
                              if not meta or meta.get("document_id") not in current_ids]
                if orphan_ids:
                    collection.delete(ids=orphan_ids)
        return len(docs)

    def search(self, db: Session, question: str, limit: int = 4) -> list[dict]:
        if limit <= 0:
            return []
        docs = db.scalars(select(Document)).all()
        by_id = {doc.id: doc for doc in docs}
        vector_matches = []
        try:
            with self._lock:
                collection = self._vector()
                if collection is not None and collection.count():
                    vector = self._embedder.encode([question])["dense_vecs"].tolist()
                    result = collection.query(query_embeddings=vector, n_results=min(limit * 4, collection.count()))
                    for meta, passage in zip(result["metadatas"][0], result["documents"][0]):
                        doc = by_id.get((meta or {}).get("document_id"))
                        # SQL is authoritative after a failed update or a disabled index.
                        if doc is not None and (meta or {}).get("version") == self._version(doc) and passage:
                            vector_matches.append({"title": doc.title, "snippet": passage})
                            if len(vector_matches) == limit:
                                self.last_error = False
                                return vector_matches
                self.last_error = False
        except Exception:
            self.last_error = True
            logger.warning("Vector retrieval unavailable; using current SQL text for keyword retrieval")
        query_terms = terms(question)
        matches = []
        for doc in docs:
            for part in chunks(doc.content):
                score = len(query_terms & terms(doc.title + " " + part))
                if score:
                    matches.append((score, {"title": doc.title, "snippet": part}))
        matches.sort(key=lambda row: row[0], reverse=True)
        seen = {(item["title"], item["snippet"]) for item in vector_matches}
        for _, item in matches:
            key = (item["title"], item["snippet"])
            if key not in seen:
                vector_matches.append(item)
                seen.add(key)
            if len(vector_matches) == limit:
                break
        return vector_matches


knowledge_index = KnowledgeIndex()
