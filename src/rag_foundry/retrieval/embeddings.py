"""Embedding service abstraction and deterministic mock / local providers."""

import abc
import hashlib
import json
import math
import threading
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Sequence


HttpTransport = Callable[
    [str, Dict[str, Any], Dict[str, str], float],
    Dict[str, Any],
]


def _default_http_transport(
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout: float,
) -> Dict[str, Any]:
    """Send a JSON HTTP POST request using Python's standard library.

    Args:
        url: Target HTTP/HTTPS endpoint URL.
        payload: JSON-serializable request dictionary.
        headers: HTTP headers to attach to the request.
        timeout: Request timeout in seconds.

    Returns:
        Decoded JSON response dictionary.

    Raises:
        RuntimeError: If the HTTP request fails or returns invalid JSON.
    """
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Embedding HTTP request failed ({exc.code}): {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Embedding HTTP connection error: {exc.reason}"
        ) from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Embedding endpoint returned invalid JSON: {exc}"
        ) from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(
            "Embedding endpoint JSON response must be an object."
        )
    return parsed


class EmbeddingService(abc.ABC):
    """Abstract base class for vector embedding generation."""

    @property
    @abc.abstractmethod
    def dimension(self) -> int:
        """Return the vector dimensionality of this embedding service."""
        pass

    @abc.abstractmethod
    def embed_query(self, text: str) -> List[float]:
        """Generate a dense vector embedding for a query string."""
        pass

    @abc.abstractmethod
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate dense vector embeddings for a list of chunk texts."""
        pass


class MockDeterministicEmbeddingService(EmbeddingService):
    """Deterministic, lightweight embedding service for testing and conformance verification."""

    def __init__(self, dimension: int = 384) -> None:
        """Initialize mock embedding service.

        Args:
            dimension: Dimensionality of generated vector embeddings.
        """
        if dimension <= 0:
            raise ValueError("Embedding dimension must be positive.")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        return self._dimension

    def _generate_vector(self, text: str) -> List[float]:
        """Generate a deterministic unit-normalized pseudo-vector from text hash."""
        vec: List[float] = []
        # Use multiple sha256 digest rounds to deterministically generate sufficient float components
        seed_bytes = text.encode("utf-8")
        round_idx = 0
        while len(vec) < self._dimension:
            digest = hashlib.sha256(seed_bytes + str(round_idx).encode("utf-8")).digest()
            for i in range(0, len(digest) - 3, 4):
                if len(vec) >= self._dimension:
                    break
                # Unpack 4 bytes as signed integer and convert to float in [-1.0, 1.0]
                int_val = int.from_bytes(digest[i : i + 4], byteorder="big", signed=True)
                vec.append(float(int_val) / 2147483648.0)
            round_idx += 1

        # Normalize to unit length
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:
            vec[0] = 1.0
            return vec

        return [x / norm for x in vec]

    def embed_query(self, text: str) -> List[float]:
        """Embed single query string."""
        return self._generate_vector(text)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Embed batch of texts."""
        return [self._generate_vector(t) for t in texts]


def resolve_embedding_model_name(
    embedding_service: EmbeddingService,
    override: Optional[str] = None,
) -> str:
    """Resolve canonical embedding model identifier shared by index & query.

    Args:
        embedding_service: Active EmbeddingService instance.
        override: Optional explicit model name override.

    Returns:
        Non-empty model identifier string.
    """
    if override is not None and override.strip():
        return override.strip()
    attr_name = getattr(embedding_service, "model_name", None)
    if isinstance(attr_name, str) and attr_name.strip():
        return attr_name.strip()
    return type(embedding_service).__name__


class HttpEmbeddingService(EmbeddingService):
    """HTTP embedding adapter for local/air-gapped Ollama and OpenAI servers.

    Supports Ollama (`/api/embed`) and OpenAI-compatible (`/v1/embeddings`)
    endpoints such as vLLM or Text Embeddings Inference (TEI) using only the
    Python standard library unless a custom transport is injected.
    """

    _SUPPORTED_PROVIDERS = frozenset({"ollama", "openai"})

    def __init__(
        self,
        base_url: str,
        model_name: str,
        dimension: int,
        provider: str = "ollama",
        api_key: Optional[str] = None,
        timeout_seconds: float = 30.0,
        headers: Optional[Dict[str, str]] = None,
        transport: Optional[HttpTransport] = None,
        batch_size: int = 32,
    ) -> None:
        """Initialize HttpEmbeddingService.

        Args:
            base_url: Base URL of the local or private embedding server.
            model_name: Embedding model identifier served by the endpoint.
            dimension: Expected vector dimensionality for strict validation.
            provider: Payload format, either `"ollama"` or `"openai"`.
            api_key: Optional bearer token for authenticated endpoints.
            timeout_seconds: HTTP request timeout in seconds.
            headers: Optional extra HTTP headers.
            transport: Optional callable overriding the HTTP POST transport.
            batch_size: Maximum texts sent per HTTP request (default 32).

        Raises:
            ValueError: If configuration parameters are invalid.
        """
        normalized_provider = provider.strip().lower()
        if normalized_provider not in self._SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported embedding provider: {provider!r}. "
                "Expected 'ollama' or 'openai'."
            )
        if not base_url or not base_url.strip():
            raise ValueError("base_url must be a non-empty string.")
        if not model_name or not model_name.strip():
            raise ValueError("model_name must be a non-empty string.")
        if dimension <= 0:
            raise ValueError("Embedding dimension must be positive.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive.")

        self._base_url = base_url.strip().rstrip("/")
        self.model_name = model_name.strip()
        self._dimension = dimension
        self.provider = normalized_provider
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.batch_size = batch_size
        self._headers = dict(headers) if headers is not None else {}
        self._transport = (
            transport if transport is not None else _default_http_transport
        )

    @property
    def dimension(self) -> int:
        """Return configured embedding vector dimension."""
        return self._dimension

    def _endpoint_url(self) -> str:
        """Return the provider-specific embedding endpoint URL."""
        if self.provider == "ollama":
            return f"{self._base_url}/api/embed"
        return f"{self._base_url}/v1/embeddings"

    def _build_headers(self) -> Dict[str, str]:
        """Build HTTP headers including Content-Type and optional auth."""
        req_headers = {"Content-Type": "application/json"}
        req_headers.update(self._headers)
        if self._api_key is not None:
            req_headers["Authorization"] = f"Bearer {self._api_key}"
        return req_headers

    def _parse_response(
        self,
        response: Dict[str, Any],
        expected_count: int,
    ) -> List[List[float]]:
        """Extract and validate vectors from a provider JSON response.

        Args:
            response: Decoded response JSON dictionary.
            expected_count: Number of input texts sent in the request.

        Returns:
            Validated list of float vectors matching input order.

        Raises:
            ValueError: If payload shape, vector count, or dimension is wrong.
        """
        raw_vectors: List[Any]
        if self.provider == "ollama":
            if "embeddings" in response and isinstance(
                response["embeddings"], list
            ):
                raw_vectors = response["embeddings"]
            elif (
                "embedding" in response
                and isinstance(response["embedding"], list)
                and expected_count == 1
            ):
                raw_vectors = [response["embedding"]]
            else:
                raise ValueError(
                    "Invalid Ollama response: missing 'embeddings' list."
                )
        else:
            data = response.get("data")
            if not isinstance(data, list):
                raise ValueError(
                    "Invalid OpenAI response: missing 'data' list."
                )
            indexed_items: List[tuple[int, Any]] = []
            for pos, item in enumerate(data):
                if not isinstance(item, dict) or "embedding" not in item:
                    raise ValueError(
                        "Invalid OpenAI response item: missing 'embedding'."
                    )
                item_idx = item.get("index", pos)
                indexed_items.append((int(item_idx), item["embedding"]))
            indexed_items.sort(key=lambda pair: pair[0])
            raw_vectors = [vec for _, vec in indexed_items]

        if len(raw_vectors) != expected_count:
            raise ValueError(
                f"Embedding count mismatch: expected {expected_count}, "
                f"got {len(raw_vectors)}."
            )

        validated: List[List[float]] = []
        for vec in raw_vectors:
            if not isinstance(vec, Sequence) or isinstance(vec, (str, bytes)):
                raise ValueError("Embedding vector must be a numeric sequence.")
            if len(vec) != self._dimension:
                raise ValueError(
                    f"Embedding dimension mismatch: expected "
                    f"{self._dimension}, got {len(vec)}."
                )
            validated.append([float(v) for v in vec])
        return validated

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate dense embeddings in size-bounded HTTP batches.

        Args:
            texts: Texts to embed.

        Returns:
            List of validated embedding vectors matching `texts` order.
        """
        if not texts:
            return []

        endpoint = self._endpoint_url()
        headers = self._build_headers()
        all_vectors: List[List[float]] = []

        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            payload: Dict[str, Any] = {
                "model": self.model_name,
                "input": batch,
            }
            response = self._transport(
                endpoint,
                payload,
                headers,
                self.timeout_seconds,
            )
            all_vectors.extend(
                self._parse_response(response, expected_count=len(batch))
            )
        return all_vectors

    def embed_query(self, text: str) -> List[float]:
        """Generate a dense embedding vector for a single query string.

        Args:
            text: Query text to embed.

        Returns:
            Single validated embedding vector.
        """
        return self.embed_texts([text])[0]


class SentenceTransformerEmbeddingService(EmbeddingService):
    """Lazy SentenceTransformers embedding adapter for local execution.

    Defers importing `sentence_transformers` until first model load so core
    deployments remain lightweight and air-gapped installations stay optional.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        dimension: Optional[int] = None,
        device: Optional[str] = None,
        normalize_embeddings: bool = True,
        model: Optional[Any] = None,
        model_loader: Optional[Callable[[str], Any]] = None,
        batch_size: Optional[int] = None,
    ) -> None:
        """Initialize SentenceTransformerEmbeddingService.

        Args:
            model_name: Local path or model name for SentenceTransformer.
            dimension: Optional explicit vector dimension for validation.
            device: Optional torch device string (e.g., `"cpu"`, `"cuda"`).
            normalize_embeddings: Whether to L2-normalize model outputs.
            model: Optional pre-loaded model instance (useful for testing).
            model_loader: Optional callable returning a model for `model_name`.
            batch_size: Optional max batch size for chunked local encoding.

        Raises:
            ValueError: If `dimension` or `batch_size` is non-positive.
        """
        if dimension is not None and dimension <= 0:
            raise ValueError("Embedding dimension must be positive.")
        if batch_size is not None and batch_size <= 0:
            raise ValueError("batch_size must be positive.")
        self.model_name = model_name
        self._dimension = dimension
        self.device = device
        self.normalize_embeddings = normalize_embeddings
        self._model = model
        self._model_loader = model_loader
        self.batch_size = batch_size
        self._load_lock = threading.Lock()

    def _load_model(self) -> Any:
        """Lazily load and cache the underlying SentenceTransformer model.

        Returns:
            Loaded model object exposing `.encode(...)`.

        Raises:
            ImportError: If `sentence_transformers` is not installed.
        """
        if self._model is not None:
            return self._model

        with self._load_lock:
            if self._model is not None:
                return self._model

            if self._model_loader is not None:
                self._model = self._model_loader(self.model_name)
                return self._model

            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise ImportError(
                    "SentenceTransformerEmbeddingService requires optional ML "
                    "dependencies. Install with: pip install 'rag-foundry[ml]'"
                ) from exc

            kwargs: Dict[str, Any] = {}
            if self.device is not None:
                kwargs["device"] = self.device
            self._model = SentenceTransformer(self.model_name, **kwargs)
            return self._model

    @property
    def dimension(self) -> int:
        """Return embedding dimension, querying the model if unset.

        Returns:
            Positive embedding vector dimension.

        Raises:
            ValueError: If the model cannot report a positive dimension.
        """
        if self._dimension is not None:
            return self._dimension

        model = self._load_model()
        getter = getattr(model, "get_sentence_embedding_dimension", None)
        if callable(getter):
            inferred = getter()
            if isinstance(inferred, int) and inferred > 0:
                self._dimension = inferred
                return self._dimension

        raise ValueError(
            "Unable to determine embedding dimension from model; "
            "provide 'dimension' explicitly."
        )

    def _validate_vectors(
        self,
        raw_vectors: Any,
        expected_count: int,
    ) -> List[List[float]]:
        """Convert model output to validated `List[List[float]]`.

        Args:
            raw_vectors: Raw output returned by `model.encode(...)`.
            expected_count: Expected number of vectors.

        Returns:
            Validated list of float vectors.

        Raises:
            ValueError: If vector count or dimensionality is inconsistent.
        """
        if hasattr(raw_vectors, "tolist"):
            raw_list = raw_vectors.tolist()
        else:
            raw_list = list(raw_vectors)

        if len(raw_list) != expected_count:
            raise ValueError(
                f"Embedding count mismatch: expected {expected_count}, "
                f"got {len(raw_list)}."
            )

        expected_dim = self._dimension
        validated: List[List[float]] = []
        for vec in raw_list:
            row = vec.tolist() if hasattr(vec, "tolist") else list(vec)
            if expected_dim is None:
                if not row:
                    raise ValueError("Model returned empty embedding vector.")
                expected_dim = len(row)
                self._dimension = expected_dim
            elif len(row) != expected_dim:
                raise ValueError(
                    f"Embedding dimension mismatch: expected {expected_dim}, "
                    f"got {len(row)}."
                )
            validated.append([float(v) for v in row])
        return validated

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate dense embeddings for a batch of texts locally.

        Args:
            texts: Texts to embed.

        Returns:
            List of validated float vectors.
        """
        if not texts:
            return []

        model = self._load_model()
        step = self.batch_size if self.batch_size is not None else len(texts)
        all_vectors: List[List[float]] = []
        for start in range(0, len(texts), step):
            batch = list(texts[start : start + step])
            raw = model.encode(
                batch,
                normalize_embeddings=self.normalize_embeddings,
            )
            all_vectors.extend(
                self._validate_vectors(raw, expected_count=len(batch))
            )
        return all_vectors

    def embed_query(self, text: str) -> List[float]:
        """Generate a dense embedding vector for a single query string.

        Args:
            text: Query string to embed.

        Returns:
            Single validated float vector.
        """
        return self.embed_texts([text])[0]
