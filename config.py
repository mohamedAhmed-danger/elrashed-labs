import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    
    # Flask Security
    SECRET_KEY = os.getenv("SECRET_KEY")
    
    # MySQL Database Configuration
    MYSQL_USER = os.getenv("MYSQL_USER")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
    MYSQL_HOST = os.getenv("MYSQL_HOST")
    MYSQL_PORT = os.getenv("MYSQL_PORT")
    MYSQL_DB = os.getenv("MYSQL_DB")

    # Full Database URI (Default to MySQL with PyMySQL driver and utf8mb4 for Arabic support)
    SQLALCHEMY_DATABASE_URI = os.getenv( "DATABASE_URL", f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"
)
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = { "pool_recycle": 280,"pool_pre_ping": True,  }

    # Pagination Defaults
    ITEMS_PER_PAGE = int(os.getenv("ITEMS_PER_PAGE", 10))
    MAX_BUNDLES = int(os.getenv("MAX_BUNDLES", 10))

    # Qdrant Vector Database
    QDRANT_URL = os.getenv("QDRANT_URL")
    QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
    VECTOR_SIZE = int(os.getenv("VECTOR_SIZE", 768))
    COLLECTION_NAME = os.getenv("COLLECTION_NAME")

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL")
    OCR_MODEL = os.getenv("OCR_MODEL") or os.getenv("OCR_MODEl")
    OCR_MODEl = OCR_MODEL  
    LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()

    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL")    

    
    
    FEEDBACK_BASE_URL = os.getenv("FEEDBACK_BASE_URL", "https://labs-mangement.revyai.tech")
    GMAIL_CREDENTIALS_PATH = os.getenv("GMAIL_CREDENTIALS_PATH")
    WEBHOOK_THREAD_POOL_SIZE = int(os.getenv("WEBHOOK_THREAD_POOL_SIZE", "8"))
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    GENERAL_SUBSCRIPTION_LAB_ID = int(os.getenv("GENERAL_SUBSCRIPTION_LAB_ID", "1"))
    