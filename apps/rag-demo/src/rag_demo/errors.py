"""Exceptions of the rag-demo app (it never imports ``pruefstand``, so it has its own root)."""


class RagDemoError(Exception):
    """Base class of every error raised by ``rag_demo``."""


class ConfigError(RagDemoError, ValueError):
    """The configuration is invalid or points at something that does not exist."""


class CorpusError(RagDemoError):
    """A corpus file is missing or does not validate against ``schemas/chunk.schema.json``."""


class EmbeddingError(RagDemoError):
    """The embedding service failed or answered in an unexpected shape."""


class EncoderError(EmbeddingError):
    """A dense encoder failed after its retries or got an unusable answer (never holds the key)."""


class RetrievalError(RagDemoError):
    """The vector store failed or answered in an unexpected shape."""


class IndexMismatchError(RetrievalError):
    """The Qdrant collection was built with another analyzer or hash scheme than the running app."""


class IndexUnavailableError(RetrievalError):
    """The collection metadata cannot be read, is incomplete or is not a Prüfstand index."""


class RerankError(RetrievalError):
    """The reranker service failed or answered in an unexpected shape (never holds a body)."""


class TenantIsolationError(RetrievalError):
    """A retrieved chunk belongs to a tenant the caller may not see (post-condition guard)."""


class UnknownTenantError(RagDemoError, ValueError):
    """The tenant id is malformed or not in the index; the API answers 422."""


class GenerationError(RagDemoError):
    """The generator failed; the message never contains credentials or response bodies."""
