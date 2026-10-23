class RagError(Exception):
    """A request the RAG services refuse. `code` is stable and machine-readable; ai/rag_views.py
    turns it into the API's {"code", "detail"} error body."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail
