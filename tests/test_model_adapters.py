"""Tests for local/air-gapped embedding and cross-encoder reranker adapters."""

import builtins
import tomllib
import uuid
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import pytest

from rag_foundry.retrieval.models import RankedChunk


def test_http_embedding_service_ollama_and_openai_payloads() -> None:
    """HttpEmbeddingService handles Ollama and OpenAI payloads and checks."""
    from rag_foundry.retrieval.embeddings import HttpEmbeddingService

    captured: List[Tuple[str, Dict[str, Any], Dict[str, str], float]] = []

    def _ollama_transport(
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        timeout: float,
    ) -> Dict[str, Any]:
        captured.append((url, payload, headers, timeout))
        return {
            "embeddings": [
                [0.1, 0.2, 0.3, 0.4] for _ in payload["input"]
            ]
        }

    ollama = HttpEmbeddingService(
        base_url="http://localhost:11434/",
        model_name="nomic-embed-text",
        dimension=4,
        provider="ollama",
        timeout_seconds=12.0,
        transport=_ollama_transport,
    )
    assert ollama.dimension == 4
    assert ollama.embed_texts([]) == []
    assert len(captured) == 0

    vecs = ollama.embed_texts(["doc one", "doc two"])
    assert len(vecs) == 2
    assert vecs[0] == [0.1, 0.2, 0.3, 0.4]
    assert captured[0][0] == "http://localhost:11434/api/embed"
    assert captured[0][1] == {
        "model": "nomic-embed-text",
        "input": ["doc one", "doc two"],
    }
    assert captured[0][3] == 12.0

    q_vec = ollama.embed_query("query text")
    assert q_vec == [0.1, 0.2, 0.3, 0.4]

    # OpenAI-compatible endpoint (vLLM / TEI) with out-of-order response indices
    openai_captured: List[Tuple[str, Dict[str, Any], Dict[str, str]]] = []

    def _openai_transport(
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        timeout: float,
    ) -> Dict[str, Any]:
        openai_captured.append((url, payload, headers))
        return {
            "data": [
                {"index": 1, "embedding": [0.9, 0.8, 0.7]},
                {"index": 0, "embedding": [0.1, 0.2, 0.3]},
            ]
        }

    openai_emb = HttpEmbeddingService(
        base_url="http://vllm.local:8000",
        model_name="bge-small",
        dimension=3,
        provider="openai",
        api_key="local-secret",
        transport=_openai_transport,
    )
    ordered = openai_emb.embed_texts(["first", "second"])
    assert ordered == [[0.1, 0.2, 0.3], [0.9, 0.8, 0.7]]
    assert openai_captured[0][0] == "http://vllm.local:8000/v1/embeddings"
    assert openai_captured[0][2]["Authorization"] == "Bearer local-secret"


def test_http_embedding_service_validation_and_error_handling() -> None:
    """HttpEmbeddingService validates config, dimensions, counts, and errors."""
    from rag_foundry.retrieval.embeddings import HttpEmbeddingService

    with pytest.raises(ValueError, match="provider"):
        HttpEmbeddingService(
            base_url="http://localhost:11434",
            model_name="m",
            dimension=4,
            provider="unsupported",
        )

    with pytest.raises(ValueError, match="dimension"):
        HttpEmbeddingService(
            base_url="http://localhost:11434",
            model_name="m",
            dimension=0,
        )

    bad_dim = HttpEmbeddingService(
        base_url="http://localhost:11434",
        model_name="m",
        dimension=4,
        transport=lambda u, p, h, t: {"embeddings": [[0.1, 0.2]]},
    )
    with pytest.raises(ValueError, match="dimension mismatch"):
        bad_dim.embed_query("hello")

    bad_count = HttpEmbeddingService(
        base_url="http://localhost:11434",
        model_name="m",
        dimension=2,
        transport=lambda u, p, h, t: {"embeddings": [[0.1, 0.2]]},
    )
    with pytest.raises(ValueError, match="count mismatch"):
        bad_count.embed_texts(["a", "b"])

    def _failing_transport(
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        timeout: float,
    ) -> Dict[str, Any]:
        raise RuntimeError("connection refused")

    failing = HttpEmbeddingService(
        base_url="http://localhost:11434",
        model_name="m",
        dimension=2,
        transport=_failing_transport,
    )
    with pytest.raises(RuntimeError, match="connection refused"):
        failing.embed_query("hello")


def test_sentence_transformer_embedding_lazy_and_mocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SentenceTransformerEmbeddingService supports mock backend & clear err."""
    from rag_foundry.retrieval.embeddings import (
        SentenceTransformerEmbeddingService,
    )

    class _FakeSTModel:
        def get_sentence_embedding_dimension(self) -> int:
            return 3

        def encode(
            self,
            texts: List[str],
            normalize_embeddings: bool = True,
        ) -> List[List[float]]:
            assert normalize_embeddings is True
            return [[0.5, 0.5, 0.5] for _ in texts]

    svc = SentenceTransformerEmbeddingService(
        model_name="BAAI/bge-small-en-v1.5",
        model_loader=lambda name: _FakeSTModel(),
    )
    assert svc.dimension == 3
    assert svc.embed_texts([]) == []
    assert svc.embed_query("alpha") == [0.5, 0.5, 0.5]
    assert svc.embed_texts(["a", "b"]) == [[0.5, 0.5, 0.5], [0.5, 0.5, 0.5]]

    # Simulate uninstalled sentence_transformers -> actionable ImportError
    real_import = builtins.__import__

    def _missing_st(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sentence_transformers":
            raise ImportError("No module named 'sentence_transformers'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _missing_st)
    uninstalled = SentenceTransformerEmbeddingService(
        model_name="BAAI/bge-small-en-v1.5",
        dimension=384,
    )
    with pytest.raises(ImportError, match="rag-foundry\\[ml\\]"):
        uninstalled.embed_query("test")


def test_cross_encoder_reranker_normalization_tiebreak_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CrossEncoderReranker normalizes scores, tie-breaks, controls fallback."""
    from rag_foundry.retrieval.reranking import CrossEncoderReranker

    ws_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    id_a = uuid.UUID("00000000-0000-0000-0000-00000000000a")
    id_b = uuid.UUID("00000000-0000-0000-0000-00000000000b")
    id_c = uuid.UUID("00000000-0000-0000-0000-00000000000c")

    c_b = RankedChunk(
        chunk_id=id_b,
        document_version_id=doc_id,
        workspace_id=ws_id,
        text="Secondary tied chunk",
        score=0.2,
    )
    c_a = RankedChunk(
        chunk_id=id_a,
        document_version_id=doc_id,
        workspace_id=ws_id,
        text="Primary tied chunk",
        score=0.2,
    )
    c_c = RankedChunk(
        chunk_id=id_c,
        document_version_id=doc_id,
        workspace_id=ws_id,
        text="Top relevant chunk",
        score=0.1,
    )

    # 1. Custom scorer with raw logits -> sigmoid normalization + tie-break
    def _logit_scorer(pairs: List[Tuple[str, str]]) -> Sequence[float]:
        scores: List[float] = []
        for _, text in pairs:
            if "Top relevant" in text:
                scores.append(4.0)
            else:
                scores.append(-1.0)
        return scores

    reranker = CrossEncoderReranker(
        scorer=_logit_scorer,
        allow_fallback=False,
        normalization="sigmoid",
    )
    assert reranker.rerank("query", [], top_k=3) == []
    ranked = reranker.rerank("query", [c_b, c_a, c_c], top_k=3)
    assert [c.chunk_id for c in ranked] == [id_c, id_a, id_b]
    assert all(0.0 <= c.score <= 1.0 for c in ranked)
    assert ranked[0].score > ranked[1].score == ranked[2].score

    # 2. Min-max normalization maps highest -> 1.0 and lowest -> 0.0
    mm_reranker = CrossEncoderReranker(
        scorer=_logit_scorer,
        allow_fallback=False,
        normalization="minmax",
    )
    mm_ranked = mm_reranker.rerank("query", [c_b, c_c], top_k=2)
    assert mm_ranked[0].chunk_id == id_c
    assert mm_ranked[0].score == 1.0
    assert mm_ranked[1].score == 0.0

    # Equal logits under minmax map to 0.5 with deterministic tie-break
    eq_reranker = CrossEncoderReranker(
        scorer=lambda pairs: [2.0 for _ in pairs],
        allow_fallback=False,
        normalization="minmax",
    )
    eq_ranked = eq_reranker.rerank("query", [c_b, c_a], top_k=2)
    assert [c.chunk_id for c in eq_ranked] == [id_a, id_b]
    assert eq_ranked[0].score == 0.5

    # Pre-loaded model with .predict() returning numpy-like .tolist() object
    class _FakeArray:
        def __init__(self, values: List[float]) -> None:
            self._values = values

        def tolist(self) -> List[float]:
            return list(self._values)

    class _FakeCrossEncoderModel:
        def predict(self, pairs: List[Tuple[str, str]]) -> _FakeArray:
            vals = [0.0 if "Primary" in t else 3.0 for _, t in pairs]
            return _FakeArray(vals)

    preloaded = CrossEncoderReranker(
        model=_FakeCrossEncoderModel(),
        allow_fallback=False,
    )
    pre_ranked = preloaded.rerank("query", [c_a, c_c], top_k=2)
    assert pre_ranked[0].chunk_id == id_c

    # Validation: bad normalization & score count mismatch
    with pytest.raises(ValueError, match="Unsupported normalization"):
        CrossEncoderReranker(normalization="invalid")
    bad_len = CrossEncoderReranker(scorer=lambda pairs: [1.0])
    with pytest.raises(ValueError, match="score count mismatch"):
        bad_len.rerank("query", [c_a, c_b], top_k=2)

    # 3. Missing sentence_transformers with allow_fallback=False -> ImportError
    real_import = builtins.__import__

    def _missing_st(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sentence_transformers":
            raise ImportError("No module named 'sentence_transformers'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _missing_st)
    strict_reranker = CrossEncoderReranker(
        model_name="cross-encoder/ms-marco-MiniLM-L-6-v2",
        allow_fallback=False,
    )
    with pytest.raises(ImportError, match="rag-foundry\\[ml\\]"):
        strict_reranker.rerank("query", [c_c], top_k=1)

    # 4. Explicit allow_fallback=True falls back cleanly and caches failure
    load_attempts = 0
    orig_import = builtins.__import__

    def _counting_missing_st(name: str, *args: Any, **kwargs: Any) -> Any:
        nonlocal load_attempts
        if name == "sentence_transformers":
            load_attempts += 1
            raise ImportError("No module named 'sentence_transformers'")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _counting_missing_st)
    fb_reranker = CrossEncoderReranker(
        model_name="cross-encoder/ms-marco-MiniLM-L-6-v2",
        allow_fallback=True,
    )
    for _ in range(3):
        fb_ranked = fb_reranker.rerank("Top relevant", [c_a, c_c], top_k=2)
        assert fb_ranked[0].chunk_id == id_c
    # Failure is cached after the first attempt (never retried on every call)
    assert load_attempts == 1


def test_embedding_adapters_batching_for_server_limits() -> None:
    """HttpEmbeddingService and SentenceTransformer split large inputs."""
    from rag_foundry.retrieval.embeddings import (
        HttpEmbeddingService,
        SentenceTransformerEmbeddingService,
    )

    batch_sizes_seen: List[int] = []

    def _batched_openai(
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        timeout: float,
    ) -> Dict[str, Any]:
        batch = payload["input"]
        batch_sizes_seen.append(len(batch))
        # Return reverse-indexed items to verify per-batch reordering
        items = [
            {"index": i, "embedding": [float(len(txt)), float(i)]}
            for i, txt in enumerate(batch)
        ]
        items.reverse()
        return {"data": items}

    svc = HttpEmbeddingService(
        base_url="http://tei.local:8080",
        model_name="bge-small",
        dimension=2,
        provider="openai",
        batch_size=2,
        transport=_batched_openai,
    )
    texts = ["a", "bb", "ccc", "dddd", "eeeee"]
    vectors = svc.embed_texts(texts)
    assert batch_sizes_seen == [2, 2, 1]
    assert vectors == [
        [1.0, 0.0],
        [2.0, 1.0],
        [3.0, 0.0],
        [4.0, 1.0],
        [5.0, 0.0],
    ]

    with pytest.raises(ValueError, match="batch_size"):
        HttpEmbeddingService(
            base_url="http://x", model_name="m", dimension=2, batch_size=0
        )

    st_batches: List[int] = []

    class _BatchedSTModel:
        def encode(
            self,
            batch: List[str],
            normalize_embeddings: bool = True,
        ) -> List[List[float]]:
            st_batches.append(len(batch))
            return [[float(len(t)), 1.0] for t in batch]

    st_svc = SentenceTransformerEmbeddingService(
        dimension=2,
        model=_BatchedSTModel(),
        batch_size=2,
    )
    assert len(st_svc.embed_texts(texts)) == 5
    assert st_batches == [2, 2, 1]

    with pytest.raises(ValueError, match="batch_size"):
        SentenceTransformerEmbeddingService(dimension=2, batch_size=0)


def test_default_http_transport_and_payload_edge_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default stdlib HTTP transport and payload edge cases behave safely."""
    import io
    import json
    import urllib.error
    import urllib.request

    from rag_foundry.retrieval.embeddings import (
        HttpEmbeddingService,
        SentenceTransformerEmbeddingService,
        _default_http_transport,
    )

    class _FakeResponse:
        def __init__(self, body: str) -> None:
            self._body = body.encode("utf-8")

        def read(self) -> bytes:
            return self._body

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

    # Successful POST via stdlib urlopen + Ollama legacy single-vector key
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=30.0: _FakeResponse(
            json.dumps({"embedding": [0.25, 0.75]})
        ),
    )
    svc = HttpEmbeddingService(
        base_url="http://localhost:11434",
        model_name="nomic-embed-text",
        dimension=2,
        provider="ollama",
    )
    assert svc.embed_query("hi") == [0.25, 0.75]

    # HTTPError -> RuntimeError
    def _raise_http(req: Any, timeout: float = 30.0) -> Any:
        raise urllib.error.HTTPError(
            req.full_url,
            502,
            "Bad Gateway",
            hdrs={},  # type: ignore[arg-type]
            fp=io.BytesIO(b"upstream down"),
        )

    monkeypatch.setattr(urllib.request, "urlopen", _raise_http)
    with pytest.raises(RuntimeError, match="502"):
        _default_http_transport("http://localhost:11434/api/embed", {}, {}, 5.0)

    # URLError -> RuntimeError
    def _raise_url(req: Any, timeout: float = 30.0) -> Any:
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(urllib.request, "urlopen", _raise_url)
    with pytest.raises(RuntimeError, match="connection error"):
        _default_http_transport("http://localhost:11434/api/embed", {}, {}, 5.0)

    # Invalid JSON & non-object JSON -> RuntimeError
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=30.0: _FakeResponse("not-json"),
    )
    with pytest.raises(RuntimeError, match="invalid JSON"):
        _default_http_transport("http://localhost:11434/api/embed", {}, {}, 5.0)

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=30.0: _FakeResponse("[1, 2, 3]"),
    )
    with pytest.raises(RuntimeError, match="must be an object"):
        _default_http_transport("http://localhost:11434/api/embed", {}, {}, 5.0)

    # Invalid config & malformed OpenAI/Ollama response payloads
    with pytest.raises(ValueError, match="base_url"):
        HttpEmbeddingService(base_url="", model_name="m", dimension=2)
    with pytest.raises(ValueError, match="model_name"):
        HttpEmbeddingService(base_url="http://x", model_name=" ", dimension=2)
    with pytest.raises(ValueError, match="timeout_seconds"):
        HttpEmbeddingService(
            base_url="http://x",
            model_name="m",
            dimension=2,
            timeout_seconds=0,
        )

    bad_ollama = HttpEmbeddingService(
        base_url="http://x",
        model_name="m",
        dimension=2,
        provider="ollama",
        transport=lambda u, p, h, t: {"unexpected": []},
    )
    with pytest.raises(ValueError, match="Invalid Ollama response"):
        bad_ollama.embed_query("a")

    bad_openai = HttpEmbeddingService(
        base_url="http://x",
        model_name="m",
        dimension=2,
        provider="openai",
        transport=lambda u, p, h, t: {"data": [{"index": 0}]},
    )
    with pytest.raises(ValueError, match="missing 'embedding'"):
        bad_openai.embed_query("a")

    bad_openai_list = HttpEmbeddingService(
        base_url="http://x",
        model_name="m",
        dimension=2,
        provider="openai",
        transport=lambda u, p, h, t: {"data": "not-a-list"},
    )
    with pytest.raises(ValueError, match="missing 'data'"):
        bad_openai_list.embed_query("a")

    # SentenceTransformer validation edge cases (dimension inference & errors)
    class _ArrayLike:
        def __init__(self, rows: List[List[float]]) -> None:
            self._rows = rows

        def tolist(self) -> List[List[float]]:
            return list(self._rows)

    class _NoDimModel:
        def encode(
            self,
            texts: List[str],
            normalize_embeddings: bool = True,
        ) -> _ArrayLike:
            return _ArrayLike([[1.0, 2.0] for _ in texts])

    inferred_svc = SentenceTransformerEmbeddingService(model=_NoDimModel())
    with pytest.raises(ValueError, match="Unable to determine"):
        _ = inferred_svc.dimension
    assert inferred_svc.embed_texts(["one"]) == [[1.0, 2.0]]
    assert inferred_svc.dimension == 2

    with pytest.raises(ValueError, match="dimension"):
        SentenceTransformerEmbeddingService(dimension=0)

    mismatch_svc = SentenceTransformerEmbeddingService(
        dimension=4,
        model=_NoDimModel(),
    )
    with pytest.raises(ValueError, match="dimension mismatch"):
        mismatch_svc.embed_query("one")


def test_pyproject_keeps_heavy_ml_packages_optional() -> None:
    """pyproject.toml exposes ml and pgvector as optional extras only."""
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    core_deps = [d.lower() for d in data["project"]["dependencies"]]
    assert not any("torch" in d for d in core_deps)
    assert not any("sentence-transformers" in d for d in core_deps)

    extras = data["project"]["optional-dependencies"]
    assert "ml" in extras
    assert any("sentence-transformers" in d.lower() for d in extras["ml"])
    assert "pgvector" in extras
    assert any("pgvector" in d.lower() for d in extras["pgvector"])
