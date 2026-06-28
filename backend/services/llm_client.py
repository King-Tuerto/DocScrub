"""LLM client stub — implemented in Piece 6."""


class LLMUnreachableError(Exception):
    pass


class LLMClient:
    def __init__(self, endpoint: str, model: str, chunk_tokens: int = 2048, overlap_tokens: int = 200):
        self.endpoint = endpoint
        self.model = model
        self.chunk_tokens = chunk_tokens
        self.overlap_tokens = overlap_tokens
        self.last_warning = None

    def detect_pii(self, text: str):
        raise NotImplementedError("Piece 6 not yet built")

    def list_models(self):
        raise NotImplementedError("Piece 6 not yet built")
