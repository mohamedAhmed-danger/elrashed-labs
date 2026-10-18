from llm.llm import get_gemini_embeddings


_embeddings_model = get_gemini_embeddings()


def build_embedding_text(
    text: str,
    description: str,
    keywords: list[str],
) -> str:

    return (
        f"name: {text} "
        f"description: {description} "
        f"keywords: {', '.join(keywords)}"
    )


def create_embedding(text: str) -> list[float]:
    """
    Convert text into a vector using LangChain Gemini Embeddings.
    """

    if not text or not text.strip():
        raise ValueError(
            "Cannot create embedding from empty text"
        )

    return _embeddings_model.embed_query(text)