import logging
from typing import Any, Dict

from graph.state import AgentState
from search.context_builder import ContextBuilder

logger = logging.getLogger(__name__)


def rag_node(state: AgentState) -> Dict[str, Any]:
    """
    Retrieve laboratory information using refined queries.
    """
    user_msg = state.get("user_message", "")
    refined_queries = state.get("refined_queries") or []

    logger.info(
        "\n" + "="*60 + "\n"
        "🚀 [RAG NODE ENTERED]\n"
        "   User Message: %s\n"
        "   Refined Queries Count: %d\n"
        + "="*60,
        user_msg,
        len(refined_queries),
    )

    if not refined_queries:
        logger.info(
            "⏭️ [RAG NODE] No refined queries in state. Skipping retrieval entirely."
        )

        return {
            "rag_context": "",
            "retrieval_usage": None,
        }

    try:
        rag_context, search_results, top_score = (
            ContextBuilder.build_rag_context(
                refined_queries
            )
        )

        logger.info(
            "✅ [RAG NODE SUCCESS]\n"
            "   Retrieved Results Count: %d\n"
            "   Top Confidence Score: %.4f\n"
            "   Injected Context Chars: %d\n"
            "   Context Snippet: %s...",
            len(search_results),
            top_score,
            len(rag_context),
            rag_context[:150].replace("\n", " ") if rag_context else "EMPTY",
        )

        return {
            "rag_context": rag_context,
            "retrieval_usage": {
                "queries_count": len(refined_queries),
                "results_count": len(search_results),
                "top_score": top_score,
            },
        }

    except Exception as exc:
        logger.exception(
            "❌ [RAG NODE FAILED] Exception during retrieval: %s",
            exc,
        )

        return {
            "rag_context": (
                "Failed to retrieve test details due to "
                "an internal search error."
            ),
            "retrieval_usage": None,
        }