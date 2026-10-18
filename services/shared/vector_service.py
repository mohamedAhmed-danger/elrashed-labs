import logging

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, PointStruct, VectorParams

from config import Config
from notification_center import send_production_alert
from utils.embedding_utils import build_embedding_text, create_embedding

logger = logging.getLogger(__name__)

qdrant_client = QdrantClient(url=Config.QDRANT_URL, api_key=Config.QDRANT_API_KEY)


def initialize_collection() -> None:
    """يجهّز الـ Collection في Qdrant لو مش موجود."""
    try:
        existing = {c.name for c in qdrant_client.get_collections().collections}
        if Config.COLLECTION_NAME in existing:
            logger.info("Collection '%s' already exists.", Config.COLLECTION_NAME)
            return

        qdrant_client.create_collection(
            collection_name=Config.COLLECTION_NAME,
            vectors_config=VectorParams(size=Config.VECTOR_SIZE, distance=Distance.COSINE),
        )
        logger.info("Collection '%s' created successfully.", Config.COLLECTION_NAME)
    except Exception as e:
        logger.exception("Qdrant collection initialization failed")
        send_production_alert(
            subject="Qdrant Initialization Failure",
            body_or_error=e,
            context={"collection_name": Config.COLLECTION_NAME, "qdrant_url": Config.QDRANT_URL},
        )


def upsert_test_vector(test_id: int, test_name: str, description: str, keywords: list[str]) -> bool:
    """
    ينشئ أو يحدّث vector التحليل في Qdrant.
    يرجّع False لو مفيش نص كافي للـ embedding (تخطي)، ويرفع exception لو Qdrant فشل.
    """
    keywords = keywords or []

    try:
        vector = create_embedding(build_embedding_text(test_name, description, keywords))
    except ValueError as e:
        logger.warning("Skipping vector upsert for test %s: %s", test_id, e)
        return False

    payload = {
        "test_id": test_id,
        "name": test_name,
        "description": description,
        "keywords": keywords,
    }

    try:
        qdrant_client.upsert(
            collection_name=Config.COLLECTION_NAME,
            points=[PointStruct(id=test_id, vector=vector, payload=payload)],
            wait=True,
        )
    except Exception as e:
        logger.exception("Qdrant upsert failed for test %s", test_id)
        send_production_alert(
            subject=f"Qdrant Upsert Failure (Test ID: {test_id})",
            body_or_error=e,
            context={"test_id": test_id, "test_name": test_name},
        )
        raise

    logger.info("Test with ID %s upserted successfully into Qdrant.", test_id)
    return True


def delete_test_vector(test_id: int) -> bool:
    """يمسح vector التحليل من Qdrant (مفيش error لو مش موجود)."""
    try:
        qdrant_client.delete(
            collection_name=Config.COLLECTION_NAME,
            points_selector=[test_id],
        )
    except Exception as e:
        logger.exception("Qdrant delete failed for test %s", test_id)
        send_production_alert(
            subject=f"Qdrant Delete Failure (Test ID: {test_id})",
            body_or_error=e,
            context={"test_id": test_id},
        )
        raise

    logger.info("Test with ID %s deleted from Qdrant.", test_id)
    return True


def get_test_vector(test_id: int):
    """يجيب vector التحليل بالـ ID، أو None لو مش موجود."""
    try:
        result = qdrant_client.retrieve(
            collection_name=Config.COLLECTION_NAME,
            ids=[test_id],
        )
    except Exception as e:
        logger.exception("Qdrant retrieve failed for test %s", test_id)
        send_production_alert(
            subject=f"Qdrant Retrieve Failure (Test ID: {test_id})",
            body_or_error=e,
            context={"test_id": test_id},
        )
        raise

    if not result:
        logger.info("Test with ID %s not found in Qdrant.", test_id)
        return None

    logger.info("Test with ID %s retrieved successfully from Qdrant.", test_id)
    return result[0]