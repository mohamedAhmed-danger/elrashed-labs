from config import Config
from langchain_openai import ChatOpenAI



def get_gemini():
    api_key = Config.OPENAI_API_KEY

    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY must be set."
        )

    return ChatOpenAI(
        model=Config.OPENAI_MODEL,
        api_key=api_key,
        use_responses_api=True,
        reasoning={"effort": "medium"},
        temperature=0.0,
    )



def get_gemini_embeddings():
    api_key = Config.GEMINI_API_KEY

    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY or GOOGLE_API_KEY must be set."
        )

    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
    except ImportError:
        raise ImportError(
            "langchain_google_genai is required for get_gemini_embeddings. "
            "Please install langchain-google-genai."
        )

    return GoogleGenerativeAIEmbeddings(
        model=Config.EMBEDDING_MODEL,
        google_api_key=api_key,
        output_dimensionality=768,
    )