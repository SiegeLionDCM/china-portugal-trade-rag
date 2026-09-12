from __future__ import annotations

import sqlite3

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    PointStruct,
    VectorParams,
)

from trade_copilot.config import Settings
from trade_copilot.domain.models import CandidateEvidence, Chunk, Jurisdiction


class Repository:
    """Versionable chunk metadata plus dense-vector storage.

    SQLite is the source of truth for the demo. Qdrant stores only searchable vectors and a
    small payload, so the full audit record remains independent from the vector engine.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._qdrant = QdrantClient(path=str(settings.qdrant_path))
        self._init_sqlite()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.settings.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sqlite(self) -> None:
        self.settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(content_hash);
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def ensure_collection(self, vector_size: int) -> None:
        names = {item.name for item in self._qdrant.get_collections().collections}
        if self.settings.collection_name not in names:
            self._qdrant.create_collection(
                collection_name=self.settings.collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )

    def has_document_hash(self, document_id: str, content_hash: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM chunks WHERE document_id = ? AND content_hash = ? LIMIT 1",
                (document_id, content_hash),
            ).fetchone()
        return row is not None

    def replace_document(self, document_id: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if not chunks:
            return
        self.ensure_collection(len(vectors[0]))
        # Delete only the exact document version target, never the whole collection.
        old_ids = []
        with self._connect() as conn:
            old_ids = [
                row["chunk_id"]
                for row in conn.execute("SELECT chunk_id FROM chunks WHERE document_id = ?", (document_id,))
            ]
            conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            conn.executemany(
                "INSERT INTO chunks(chunk_id, document_id, content_hash, payload_json) VALUES (?, ?, ?, ?)",
                [
                    (chunk.chunk_id, chunk.document_id, chunk.content_hash, chunk.model_dump_json())
                    for chunk in chunks
                ],
            )
        if old_ids:
            self._qdrant.delete(self.settings.collection_name, points_selector=old_ids, wait=True)
        points = [
            PointStruct(
                id=chunk.chunk_id,
                vector=vector,
                payload={
                    "document_id": chunk.document_id,
                    "jurisdiction": chunk.jurisdiction.value,
                    "topics": chunk.topics,
                    "language": chunk.language,
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        self._qdrant.upsert(self.settings.collection_name, points=points, wait=True)

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
        return Chunk.model_validate_json(row["payload_json"]) if row else None

    def all_chunks(
        self,
        jurisdictions: list[Jurisdiction] | None = None,
        topics: list[str] | None = None,
    ) -> list[Chunk]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM chunks ORDER BY chunk_id").fetchall()
        chunks = [Chunk.model_validate_json(row["payload_json"]) for row in rows]
        if jurisdictions:
            allowed = set(jurisdictions)
            chunks = [chunk for chunk in chunks if chunk.jurisdiction in allowed]
        if topics:
            wanted = set(topics)
            chunks = [chunk for chunk in chunks if wanted.intersection(chunk.topics)]
        return chunks

    def dense_search(
        self,
        vector: list[float],
        jurisdictions: list[Jurisdiction],
        limit: int,
        topics: list[str] | None = None,
    ) -> list[CandidateEvidence]:
        conditions = []
        if jurisdictions:
            conditions.append(
                FieldCondition(
                    key="jurisdiction",
                    match=MatchAny(any=[item.value for item in jurisdictions]),
                )
            )
        if topics:
            conditions.append(FieldCondition(key="topics", match=MatchAny(any=topics)))
        result = self._qdrant.query_points(
            collection_name=self.settings.collection_name,
            query=vector,
            query_filter=Filter(must=conditions) if conditions else None,
            limit=limit,
            with_payload=False,
        ).points
        candidates = []
        for rank, point in enumerate(result, start=1):
            chunk = self.get_chunk(str(point.id))
            if chunk:
                candidates.append(
                    CandidateEvidence(chunk=chunk, dense_rank=rank, fused_score=float(point.score))
                )
        return candidates

    def add_feedback(self, request_id: str, category: str, note: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO feedback(request_id, category, note) VALUES (?, ?, ?)",
                (request_id, category, note),
            )

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            chunks = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
            documents = conn.execute("SELECT COUNT(DISTINCT document_id) AS n FROM chunks").fetchone()["n"]
        return {"documents": documents, "chunks": chunks}

    def close(self) -> None:
        self._qdrant.close()
