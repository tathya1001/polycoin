import httpx
from django.conf import settings

BATCH_SIZE = 64

class AIError(Exception):
    """Typed failure with a machine-readable `code`, like ImportProblem in transactions/views.py.

    Never put narration text or vectors in `detail`: it ends up in logs and API responses.
    """
    
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        
class OllamaClient:
    def __init__(
        self, base_url: str | None = None, timeout: float | None = None, api_key: str | None = None
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.timeout = timeout or settings.OLLAMA_TIMEOUT
        key = settings.OLLAMA_API_KEY if api_key is None else api_key
        # Plain Ollama ignores this header; the gateway in front of a remote Ollama rejects
        # requests without it. The key is never put in an AIError.
        self.headers = {"Authorization": f"Bearer {key}"} if key else {}
        
    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = httpx.request(
                method, self.base_url + path, timeout=self.timeout, headers=self.headers, **kwargs
            )
        except httpx.TransportError:
            # Covers connection refused, DNS failure and timeouts. `from None` drops the
            # original exception so nothing from the request leaks into the traceback.
            raise AIError(
                "ollama_unreachable",
                "Could not reach the Ollama server. Check the OLLAMA_BASE_URL environment variable and that the server is running.",
            ) from None

        if response.status_code == 401:
            raise AIError(
                "ollama_unauthorized",
                "The Ollama gateway rejected the API key. Check the OLLAMA_API_KEY environment variable.",
            )
        return response
    
    def list_models(self) -> list[dict]:
        """Installed models that can produce embeddings, as [{"name", "dimension"}]."""
        response = self._request("GET", "/api/tags")
        if response.status_code != 200:
            raise AIError("ollama_unreachable", "Ollama answered, but not with a model list.")

        models = []
        for entry in response.json().get("models", []):
            capabilities = entry.get("capabilities")
            if capabilities is None:
                is_embedder = "embed" in entry["name"].lower()
            else:
                is_embedder = "embedding" in capabilities

            if is_embedder:
                models.append(
                    {
                        "name": entry["name"],
                        "dimension": entry.get("details", {}).get("embedding_length"),
                    }
                )

        if not models:
            raise AIError(
                "no_embedding_models",
                "Ollama has no embedding model installed. Run: ollama pull nomic-embed-text",
            )
        return models
    
    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """One vector per text, in order. All vectors share one dimension or this raises"""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            response = self._request("POST", "/api/embed", json={"model": model, "input": batch})
            
            if response.status_code == 404:
                raise AIError("model_not_found", f"Model '{model}' isn't installed in Ollama.")
            if response.status_code != 200:
                raise AIError("embedding_failed", f"Ollama failed to embed a batch (HTTP {response.status_code}).")
            
            returned = response.json().get("embeddings") or []
            if len(returned) != len(batch):
                raise AIError(
                    "embedding_failed",
                    "Ollama returned the wrong number of vectors."
                )
            vectors.extend(returned)
            
            if len({len(v) for v in vectors}) > 1:
                raise AIError(
                    "dimension_mismatch",
                    "Ollama returned vectors of different sizes."
                )
                
        return vectors