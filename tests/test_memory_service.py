from pathlib import Path

from JavPI.memory.service import MemoryService, SqliteMemoryStore


class _FakeEmbedder:
    def embed_document(self, text: str):
        return self._vectorize(text)

    def embed_query(self, text: str):
        return self._vectorize(text)

    def _vectorize(self, text: str):
        lowered = text.lower()
        if "pricing" in lowered:
            return [1.0, 0.0]
        if "founder" in lowered:
            return [0.0, 1.0]
        return [0.2, 0.2]


def _service(tmp_path: Path, embedder=None) -> MemoryService:
    store = SqliteMemoryStore(tmp_path / "memory.db")
    return MemoryService(store=store, embedder=embedder)


def test_save_and_recent_returns_persisted_memory(tmp_path):
    service = _service(tmp_path)

    record = service.save(
        title="OpenAI pricing note",
        summary="The page had a monthly team pricing comparison.",
        content="Save the pricing notes for later.",
        source="browser",
        url="https://example.com/pricing",
        tags=["pricing", "team", "pricing"],
    )

    recent = service.recent(limit=3)

    assert record.title == "OpenAI pricing note"
    assert list(record.tags) == ["pricing", "team"]
    assert len(recent) == 1
    assert recent[0].title == "OpenAI pricing note"
    assert recent[0].url == "https://example.com/pricing"


def test_search_returns_lexical_matches(tmp_path):
    service = _service(tmp_path)
    service.save(
        title="Founder market map",
        summary="List of AI competitors and notes.",
        content="This captures the competitor map from the founder session.",
        source="research",
        tags=["market", "founder"],
    )
    service.save(
        title="Pricing page notes",
        summary="Billing tiers and seats.",
        content="This memory contains pricing details.",
        source="browser",
        tags=["pricing"],
    )

    hits = service.search("competitor founder notes", limit=5)

    assert hits
    assert hits[0].title == "Founder market map"


def test_search_uses_semantic_signal_when_embedder_is_available(tmp_path):
    service = _service(tmp_path, embedder=_FakeEmbedder())
    service.save(
        title="Notes from company page",
        summary="The page focused on billing and pricing.",
        content="Pricing tiers and billing plans were the key points.",
        source="browser",
    )
    service.save(
        title="Founder interview",
        summary="An interview about culture and hiring.",
        content="No pricing details here.",
        source="video",
    )

    hits = service.search("pricing", limit=2)

    assert len(hits) == 2
    assert hits[0].title == "Notes from company page"
    assert hits[0].semantic_score >= hits[1].semantic_score


def test_delete_removes_memory(tmp_path):
    service = _service(tmp_path)
    record = service.save(
        title="Temporary note",
        summary="Delete me later.",
        content="Short-lived memory.",
    )

    assert service.delete(record.memory_id) is True
    assert service.delete(record.memory_id) is False
    assert service.recent(limit=5) == []
