import logging
from typing import Any, Dict, List

from search.fuzzy_search import fuzzy_search
from search.semantic_search import semantic_search
from search.merger import merge_results
from search.db_queries import get_all_active_lab_services_for_search

logger = logging.getLogger(__name__)

CONTEXT_BUDGET = 50


def run_search(refined_queries: List[Any]) -> Dict[str, Any]:
    """
    Execute fuzzy and semantic search across active laboratory services
    for each refined query, then merge and rank the results.
    """
    logger.info("🔎 [SEARCH MANAGER START] Received %d queries to search", len(refined_queries or []))

    if not refined_queries:
        logger.warning("⚠️ [SEARCH MANAGER] No queries passed to run_search.")
        return {
            "results": [],
            "top_score": 0.0,
        }

    # 1. Load active lab services from DB
    try:
        lab_services = get_all_active_lab_services_for_search()
        logger.info("📚 [SEARCH MANAGER] Loaded %d active lab services from DB for fuzzy matching", len(lab_services))
    except Exception:
        logger.exception("[SEARCH MANAGER] Failed to load active lab services from database")
        return {
            "results": [],
            "top_score": 0.0,
        }

    all_results = []

    # 2. Run fuzzy + semantic search for each refined query
    for idx, item in enumerate(refined_queries, 1):
        query_text = getattr(item, 'query', str(item))
        logger.info("🔹 [SEARCH MANAGER] Processing Query #%d: '%s'", idx, query_text)

        # Fuzzy Search
        try:
            f_results = fuzzy_search(
                query=item.query,
                aliases=item.aliases,
                keywords=item.keywords,
                lab_services=lab_services,
                limit=2,
            )
            logger.info("  ├─ [Fuzzy Search] Query #%d returned %d matches", idx, len(f_results))
            all_results.extend(f_results)
        except Exception:
            logger.exception("[SEARCH MANAGER] Fuzzy search failed for query: %s", query_text)

        # Semantic Search
        try:
            s_results = semantic_search(
                query=item.query,
                description=item.description,
                keywords=item.keywords,
                limit=3,
            )
            logger.info("  └─ [Semantic Search] Query #%d returned %d matches", idx, len(s_results))
            all_results.extend(s_results)
        except Exception:
            logger.exception("[SEARCH MANAGER] Semantic search failed for query: %s", query_text)

    logger.info("📊 [SEARCH MANAGER] Total raw matches collected (Fuzzy + Semantic): %d", len(all_results))

    # 3. Merge & deduplicate results
    results = merge_results(all_results)
    logger.info("🔀 [SEARCH MANAGER] Matches after merge & deduplication: %d", len(results))

    # 4. Sort by score descending
    results.sort(key=lambda r: r.score, reverse=True)

    # 5. Keep top 50 results
    results = results[:CONTEXT_BUDGET]

    top_score = results[0].score if results else 0.0

    if results:
        logger.info("🏆 [SEARCH MANAGER] Top Result: Test ID=%s | Score=%.4f | Source=%s", results[0].id, results[0].score, getattr(results[0], 'source', 'N/A'))
    else:
        logger.warning("⚠️ [SEARCH MANAGER] No merged results found after search execution.")

    logger.info(
        "✅ [SEARCH MANAGER END] Search complete | queries=%d | raw=%d | final_merged=%d | top_score=%.4f",
        len(refined_queries),
        len(all_results),
        len(results),
        top_score,
    )

    return {
        "results": results,
        "top_score": top_score,
    }