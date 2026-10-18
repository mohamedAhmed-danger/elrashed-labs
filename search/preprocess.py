import re
from typing import Set


def normalize(text: str) -> str:
    """Normalize text by lowercasing and stripping punctuation/extra whitespace."""
    if not text:
        return ""

    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def generate_ngrams(text: str, n: int = 2) -> Set[str]:
    """Generate padded character n-grams from words in text."""
    if not text:
        return set()

    ngrams = set()

    for word in text.split():
        padded_word = f"${word}$"

        if len(padded_word) < n:
            ngrams.add(padded_word)
            continue

        for i in range(len(padded_word) - n + 1):
            ngrams.add(padded_word[i:i + n])

    return ngrams


def ngram_similarity(
    query_ngrams: Set[str],
    candidate_ngrams: Set[str],
) -> float:
    """Calculate Jaccard similarity between query and candidate n-gram sets."""
    if not query_ngrams or not candidate_ngrams:
        return 0.0

    intersection = len(
        query_ngrams & candidate_ngrams
    )

    union = len(
        query_ngrams | candidate_ngrams
    )

    return intersection / union
