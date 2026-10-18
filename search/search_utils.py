from search.preprocess import normalize


def prepare_search_terms(
    query: str,
    aliases: list[str] | None = None,
    keywords: list[str] | None = None,
) -> list[str]:

    terms = [
        query,
        *(aliases or []),
        *(keywords or []),
    ]

    results = []

    for term in terms:

        if not term:
            continue

        normalized_term = normalize(term)

        if normalized_term:
            results.append(normalized_term)

    return results
