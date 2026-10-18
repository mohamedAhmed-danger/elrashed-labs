import logging
from typing import List, Optional

from qdrant_client import QdrantClient

from config import Config
from schemas.search import SearchResult
from utils.embedding_utils import build_embedding_text, create_embedding

logger = logging.getLogger(__name__)


_qdrant_client: Optional[QdrantClient] = None


def get_qdrant_client() -> QdrantClient:
    """Lazy singleton for QdrantClient with configuration validation."""
    global _qdrant_client
    if _qdrant_client is None:
        if not Config.QDRANT_URL:
            logger.warning(
                "⚠️ [QDRANT] Config.QDRANT_URL is not set or empty. "
                "QdrantClient will initialize in local/in-memory mode, which may yield empty semantic search results."
            )
        _qdrant_client = QdrantClient(
            url=Config.QDRANT_URL,
            api_key=Config.QDRANT_API_KEY,
        )
    return _qdrant_client


def _create_query_embedding(search_text: str) -> list:
    """Create an embedding vector for the search text."""
    return create_embedding(search_text)


def _query_qdrant(
    query_vector: list,
    limit: int,
):
    """Query Qdrant and return the matching points."""
    client = get_qdrant_client()
    return client.query_points(
        collection_name=Config.COLLECTION_NAME,
        query=query_vector,
        limit=limit,
    )


def _build_search_results(response) -> List[SearchResult]:
    """Convert Qdrant points into SearchResult objects."""

    return [
        SearchResult(
            id=int(point.id),
            name=(point.payload or {}).get("name", ""),
            score = max(0.0, min(1.0, round(point.score, 3))),
            source="semantic",
        )
        for point in response.points
    ]


def semantic_search(
    query: str,
    description: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    limit: int = 3,
) -> List[SearchResult]:
    """Execute semantic vector search using Qdrant."""

    if not query:
        return []

    search_text = build_embedding_text(
        text=query,
        description=description or "",
        keywords=keywords or [],
    )

    try:
        query_vector = _create_query_embedding(search_text)

        response = _query_qdrant(
            query_vector,
            limit,
        )

        return _build_search_results(response)

    except Exception:
        logger.exception(
            "[SEARCH] Semantic search failed | query=%s",
            query,
        )
        return []


def __getattr__(name: str):
    if name == "qdrant_client":
        return get_qdrant_client()


    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")