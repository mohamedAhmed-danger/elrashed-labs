from schemas.search import SearchResult


BOTH_SOURCES_BOOST = 1.15


def merge_results(results: list[SearchResult]) -> list[SearchResult]:
    best_results = {}
    sources = {}

    for result in results:
        sources.setdefault(result.id, set()).add(result.source)

        if (
            result.id not in best_results
            or result.score > best_results[result.id].score
        ):
            best_results[result.id] = result

    merged = []

    for test_id, result in best_results.items():
        source_list = sources[test_id]

        score = result.score

        if len(source_list) > 1:
            score = min(score * BOTH_SOURCES_BOOST, 1.0)

        merged.append(
            SearchResult(
                id=test_id,
                name=result.name,
                score=round(score, 3),
                source="+".join(sorted(source_list)),
            )
        )

    return merged