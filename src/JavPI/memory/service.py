import json
import math
import os
import re
import sqlite3
import threading
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

from google import genai
from google.genai import types


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _normalize_space(value).lower()).strip()


def _tokenize(value: str) -> set[str]:
    return {token for token in _normalize_text(value).split() if token}


def _normalize_tags(tags: Optional[Sequence[str] | str]) -> list[str]:
    if not tags:
        return []
    if isinstance(tags, str):
        raw = re.split(r"[,;|]", tags)
    else:
        raw = list(tags)

    normalized: list[str] = []
    seen: set[str] = set()
    for tag in raw:
        item = _normalize_space(str(tag))
        if not item:
            continue
        lowered = item.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(item)
    return normalized


def _truncate(value: str, limit: int) -> str:
    value = _normalize_space(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def _coerce_vector(values: Optional[Iterable[float]]) -> Optional[list[float]]:
    if not values:
        return None
    vector = [float(value) for value in values]
    return vector or None


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0

    dot = 0.0
    left_mag = 0.0
    right_mag = 0.0
    for left_value, right_value in zip(left, right):
        dot += left_value * right_value
        left_mag += left_value * left_value
        right_mag += right_value * right_value

    if left_mag <= 0.0 or right_mag <= 0.0:
        return 0.0
    return dot / (math.sqrt(left_mag) * math.sqrt(right_mag))


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    title: str
    summary: str
    content: str
    source: str
    url: str
    tags: tuple[str, ...]
    created_at: str
    updated_at: str
    embedding: Optional[tuple[float, ...]] = None

    @property
    def search_blob(self) -> str:
        return " ".join(
            part
            for part in (
                self.title,
                self.summary,
                self.content,
                self.source,
                self.url,
                " ".join(self.tags),
            )
            if part
        )


@dataclass(frozen=True)
class MemoryHit:
    memory_id: str
    title: str
    summary: str
    source: str
    url: str
    tags: tuple[str, ...]
    created_at: str
    updated_at: str
    score: float
    lexical_score: float
    semantic_score: float

    def to_dict(self) -> dict:
        return {
            "id": self.memory_id,
            "title": self.title,
            "summary": self.summary,
            "source": self.source,
            "url": self.url,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "score": round(self.score, 4),
            "lexical_score": round(self.lexical_score, 4),
            "semantic_score": round(self.semantic_score, 4),
        }


class MemoryServiceError(Exception):
    pass


class SqliteMemoryStore:
    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    url TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    embedding_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memories_updated_at
                ON memories(updated_at DESC)
                """
            )
            self._conn.commit()

    def upsert(self, record: MemoryRecord) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO memories (
                    memory_id,
                    title,
                    summary,
                    content,
                    source,
                    url,
                    tags_json,
                    embedding_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    title = excluded.title,
                    summary = excluded.summary,
                    content = excluded.content,
                    source = excluded.source,
                    url = excluded.url,
                    tags_json = excluded.tags_json,
                    embedding_json = excluded.embedding_json,
                    updated_at = excluded.updated_at
                """,
                (
                    record.memory_id,
                    record.title,
                    record.summary,
                    record.content,
                    record.source,
                    record.url,
                    json.dumps(list(record.tags)),
                    json.dumps(list(record.embedding)) if record.embedding else None,
                    record.created_at,
                    record.updated_at,
                ),
            )
            self._conn.commit()

    def delete(self, memory_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM memories WHERE memory_id = ?",
                (memory_id,),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def get(self, memory_id: str) -> Optional[MemoryRecord]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memories WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        return self._row_to_record(row)

    def list_recent(self, limit: int = 5) -> list[MemoryRecord]:
        safe_limit = max(1, min(int(limit), 20))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM memories
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [record for row in rows if (record := self._row_to_record(row))]

    def all_records(self, limit: int = 500) -> list[MemoryRecord]:
        safe_limit = max(1, min(int(limit), 2000))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM memories
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [record for row in rows if (record := self._row_to_record(row))]

    def _row_to_record(self, row: Optional[sqlite3.Row]) -> Optional[MemoryRecord]:
        if row is None:
            return None
        tags = tuple(json.loads(row["tags_json"] or "[]"))
        embedding_raw = row["embedding_json"]
        embedding = None
        if embedding_raw:
            embedding = tuple(float(value) for value in json.loads(embedding_raw))
        return MemoryRecord(
            memory_id=str(row["memory_id"]),
            title=str(row["title"]),
            summary=str(row["summary"]),
            content=str(row["content"]),
            source=str(row["source"]),
            url=str(row["url"]),
            tags=tags,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            embedding=embedding,
        )


class GeminiMemoryEmbedder:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-embedding-001",
        output_dimensionality: int = 768,
    ):
        self._api_key = (api_key or "").strip()
        self._model = model
        self._output_dimensionality = int(output_dimensionality)
        self._client = genai.Client(api_key=self._api_key)

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def embed_document(self, text: str) -> Optional[list[float]]:
        return self._embed(text, task_type="RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> Optional[list[float]]:
        return self._embed(text, task_type="RETRIEVAL_QUERY")

    def _embed(self, text: str, task_type: str) -> Optional[list[float]]:
        content = _truncate(text, 6000)
        if not content:
            return None

        response = self._client.models.embed_content(
            model=self._model,
            contents=content,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=self._output_dimensionality,
            ),
        )

        embeddings = getattr(response, "embeddings", None)
        if embeddings:
            first = embeddings[0]
            return _coerce_vector(getattr(first, "values", None))

        single = getattr(response, "embedding", None)
        if single:
            return _coerce_vector(getattr(single, "values", None))

        return None


class MemoryService:
    def __init__(
        self,
        store: SqliteMemoryStore,
        embedder: Optional[GeminiMemoryEmbedder] = None,
    ):
        self._store = store
        self._embedder = embedder

    @classmethod
    def from_env(cls) -> "MemoryService":
        db_path = os.getenv("JAVPI_MEMORY_DB_PATH", "").strip()
        if not db_path:
            db_path = str(Path.home() / ".javpi" / "memory.db")

        store = SqliteMemoryStore(Path(db_path))

        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        embedder = None
        if api_key:
            embedder = GeminiMemoryEmbedder(api_key=api_key)

        return cls(store=store, embedder=embedder)

    def save(
        self,
        *,
        title: str,
        summary: str,
        content: str = "",
        source: str = "agent",
        url: str = "",
        tags: Optional[Sequence[str] | str] = None,
        memory_id: Optional[str] = None,
    ) -> MemoryRecord:
        clean_title = _truncate(title or summary or content or "Untitled memory", 120)
        clean_summary = _truncate(summary or content or title, 400)
        clean_content = _truncate(content or summary or title, 4000)
        clean_source = _truncate(source or "agent", 80)
        clean_url = _truncate(url or "", 500)
        clean_tags = tuple(_normalize_tags(tags))

        if not clean_summary:
            raise MemoryServiceError("memory summary is required")

        now = _utc_now()
        existing = self._store.get(memory_id) if memory_id else None
        created_at = existing.created_at if existing else now
        resolved_memory_id = existing.memory_id if existing else (memory_id or str(uuid.uuid4()))

        embedding = None
        if self._embedder_enabled():
            try:
                embedding = self._embedder.embed_document(
                    self._render_embedding_text(
                        title=clean_title,
                        summary=clean_summary,
                        content=clean_content,
                        source=clean_source,
                        url=clean_url,
                        tags=clean_tags,
                    )
                )
            except Exception:
                embedding = None

        record = MemoryRecord(
            memory_id=resolved_memory_id,
            title=clean_title,
            summary=clean_summary,
            content=clean_content,
            source=clean_source,
            url=clean_url,
            tags=clean_tags,
            created_at=created_at,
            updated_at=now,
            embedding=tuple(embedding) if embedding else None,
        )
        self._store.upsert(record)
        return record

    def search(self, query: str, limit: int = 5) -> list[MemoryHit]:
        clean_query = _normalize_space(query)
        if not clean_query:
            raise MemoryServiceError("search query is required")

        query_embedding = None
        if self._embedder_enabled():
            try:
                query_embedding = self._embedder.embed_query(clean_query)
            except Exception:
                query_embedding = None

        query_norm = _normalize_text(clean_query)
        query_tokens = _tokenize(clean_query)
        hits: list[MemoryHit] = []

        for record in self._store.all_records(limit=max(100, int(limit) * 40)):
            lexical_score = self._lexical_score(
                query_norm=query_norm,
                query_tokens=query_tokens,
                record=record,
            )
            semantic_score = 0.0
            if query_embedding and record.embedding:
                semantic_score = max(
                    0.0,
                    _cosine_similarity(query_embedding, record.embedding),
                )

            if query_embedding and record.embedding:
                score = (0.55 * lexical_score) + (0.45 * semantic_score)
            else:
                score = lexical_score

            if score <= 0.08:
                continue

            hits.append(
                MemoryHit(
                    memory_id=record.memory_id,
                    title=record.title,
                    summary=record.summary,
                    source=record.source,
                    url=record.url,
                    tags=record.tags,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                    score=score,
                    lexical_score=lexical_score,
                    semantic_score=semantic_score,
                )
            )

        hits.sort(key=lambda item: (item.score, item.updated_at), reverse=True)
        return hits[: max(1, min(int(limit), 10))]

    def recent(self, limit: int = 5) -> list[MemoryHit]:
        hits: list[MemoryHit] = []
        for record in self._store.list_recent(limit=limit):
            hits.append(
                MemoryHit(
                    memory_id=record.memory_id,
                    title=record.title,
                    summary=record.summary,
                    source=record.source,
                    url=record.url,
                    tags=record.tags,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                    score=1.0,
                    lexical_score=1.0,
                    semantic_score=0.0,
                )
            )
        return hits

    def delete(self, memory_id: str) -> bool:
        resolved_id = _normalize_space(memory_id)
        if not resolved_id:
            raise MemoryServiceError("memory_id is required")
        return self._store.delete(resolved_id)

    def _render_embedding_text(
        self,
        *,
        title: str,
        summary: str,
        content: str,
        source: str,
        url: str,
        tags: Sequence[str],
    ) -> str:
        parts = [
            title,
            summary,
            content,
            source,
            url,
            " ".join(tags),
        ]
        return "\n".join(part for part in parts if part)

    def _embedder_enabled(self) -> bool:
        if not self._embedder:
            return False
        return bool(getattr(self._embedder, "enabled", True))

    def _lexical_score(
        self,
        *,
        query_norm: str,
        query_tokens: set[str],
        record: MemoryRecord,
    ) -> float:
        if not query_norm:
            return 0.0

        fields = {
            "title": _normalize_text(record.title),
            "summary": _normalize_text(record.summary),
            "content": _normalize_text(record.content),
            "source": _normalize_text(record.source),
            "url": _normalize_text(record.url),
            "tags": _normalize_text(" ".join(record.tags)),
            "blob": _normalize_text(record.search_blob),
        }

        score = 0.0

        if query_norm in fields["title"]:
            score += 0.55
        if query_norm in fields["summary"]:
            score += 0.35
        if query_norm in fields["content"]:
            score += 0.20
        if query_norm in fields["tags"]:
            score += 0.20
        if query_norm in fields["source"] or query_norm in fields["url"]:
            score += 0.10

        if query_tokens:
            blob_tokens = _tokenize(fields["blob"])
            overlap = len(query_tokens & blob_tokens) / len(query_tokens)
            score += 0.55 * overlap

        return min(score, 1.0)
