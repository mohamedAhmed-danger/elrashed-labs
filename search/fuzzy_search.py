import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from rapidfuzz import fuzz

from schemas.search import SearchResult
from search.db_queries import get_all_active_lab_services_for_search
from search.preprocess import (
    generate_ngrams,
    ngram_similarity,
    normalize,
)
from search.search_utils import prepare_search_terms

logger = logging.getLogger(__name__)

MIN_SCORE = 0.45

NAME_WEIGHT = 1.0
ALIAS_WEIGHT = 0.95
KEYWORD_WEIGHT = 0.85


def _build_lab_candidates(
    lab: dict,
) -> List[Tuple[str, Set[str], float]]:
    """Build normalized candidates for name, aliases, and keywords."""

    candidates = []

    normalized_name = normalize(lab.get("name", ""))

    if normalized_name:
        candidates.append(
            (
                normalized_name,
                generate_ngrams(normalized_name),
                NAME_WEIGHT,
            )
        )

    for alias in lab.get("aliases", []):
        normalized_alias = normalize(alias)

        if normalized_alias:
            candidates.append(
                (
                    normalized_alias,
                    generate_ngrams(normalized_alias),
                    ALIAS_WEIGHT,
                )
            )

    for keyword in lab.get("keywords", []):
        normalized_keyword = normalize(keyword)

        if normalized_keyword:
            candidates.append(
                (
                    normalized_keyword,
                    generate_ngrams(normalized_keyword),
                    KEYWORD_WEIGHT,
                )
            )

    return candidates


def _compare_term_to_candidate(
    search_term: str,
    term_ngrams: Set[str],
    candidate: str,
    candidate_ngrams: Set[str],
    weight: float,
) -> float:
    """Calculate the weighted similarity between a search term and candidate."""

    partial_score = fuzz.partial_ratio(
        search_term,
        candidate,
    )

    token_score = fuzz.token_set_ratio(
        search_term,
        candidate,
    )

    ngram_score = ngram_similarity(
        term_ngrams,
        candidate_ngrams,
    )

    rapid_score = max(
        partial_score,
        token_score,
    ) / 100.0

    return (
        (rapid_score + ngram_score) / 2.0
    ) * weight


def _score_lab_service(
    lab: dict,
    search_terms: List[str],
    search_term_ngrams_map: Dict[str, Set[str]],
) -> float:
    """Calculate the best fuzzy score for a lab service."""

    candidates = _build_lab_candidates(lab)

    best_score = 0.0

    for search_term in search_terms:
        current_ngrams = search_term_ngrams_map[search_term]

        for (
            candidate,
            candidate_ngrams,
            weight,
        ) in candidates:
            score = _compare_term_to_candidate(
                search_term,
                current_ngrams,
                candidate,
                candidate_ngrams,
                weight,
            )

            if score > best_score:
                best_score = score

    return best_score


def fuzzy_search(
    query: str,
    aliases: Optional[List[str]] = None,
    keywords: Optional[List[str]] = None,
    lab_services: Optional[List[dict]] = None,
    limit: int = 2,
) -> List[SearchResult]:
    """Execute fuzzy search over laboratory services."""

    search_terms = prepare_search_terms(
        query=query,
        aliases=aliases,
        keywords=keywords,
    )

    if not search_terms:
        return []

    if lab_services is None:
        lab_services = get_all_active_lab_services_for_search()

    search_term_ngrams_map = {
        term: generate_ngrams(term)
        for term in search_terms
    }

    results = []

    for lab in lab_services:
        best_score = _score_lab_service(
            lab=lab,
            search_terms=search_terms,
            search_term_ngrams_map=search_term_ngrams_map,
        )

        if best_score >= MIN_SCORE:
            results.append(
                SearchResult(
                    id=lab["id"],
                    name=lab["name"],
                    score=round(best_score, 3),
                    source="fuzzy",
                )
            )

    results.sort(
        key=lambda item: item.score,
        reverse=True,
    )

    return results[:limit]