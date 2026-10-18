# 🏥 ELsadara-agent — Medical Laboratory AI Agent & Workflow Automation Platform

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Framework-Flask-black.svg)](https://flask.palletsprojects.com/)
[![SQLAlchemy](https://img.shields.io/badge/ORM-SQLAlchemy-red.svg)](https://www.sqlalchemy.org/)
[![Qdrant](https://img.shields.io/badge/Vector_DB-Qdrant-red.svg)](https://qdrant.tech/)
[![Architecture](https://img.shields.io/badge/Pattern-Stateful_OOP_Services-green.svg)](#architecture--design-pattern)

An enterprise-grade B2B platform designed for medical diagnostic laboratories. The system unifies multichannel conversational AI, medical test booking pipelines, automated prescription OCR analysis, and laboratory management under a high-performance **Instance-Based Object-Oriented Architecture**.

---

## 📑 Table of Contents
1. [System Overview & Core Capabilities](#-system-overview--core-capabilities)
2. [Architecture & Design Pattern](#-architecture--design-pattern)
3. [System Architecture & Request Lifecycle](#-system-architecture--request-lifecycle)
4. [Application Core & Configuration (`app.py` & `config.py`)](#-application-core--configuration)
5. [Core Services Layer Breakdown (`software_services/`)](#-core-services-layer-breakdown-software_services)
6. [Routes & API Layer Breakdown (`routes/`)](#-routes--api-layer-breakdown-routes)
7. [External Integrations & AI Engines (`services/` & `llm/`)](#-external-integrations--ai-engines-services--llm)
8. [Hybrid RAG Search Pipeline (`search/`)](#-hybrid-rag-search-pipeline-search)
9. [Utility Helpers & Media Generation (`utils/`)](#-utility-helpers--media-generation-utils)
10. [Data Validation & Schemas (`schemas/`)](#-data-validation--schemas-schemas)
11. [Prescription OCR & Doctor Validation Workflow](#-prescription-ocr--doctor-validation-workflow)
12. [Database Schema & Data Model (`models/`)](#-database-schema--data-model)
13. [Bulk Ingestion & Verification Tools](#-bulk-ingestion--verification-tools)
14. [Setup & Execution Guide](#-setup--execution-guide)
15. [Quality & Verification](#-quality--verification)

---

## 🌟 System Overview & Core Capabilities

ELsadara-agent bridges laboratory management operations with patient messaging platforms (WhatsApp and Facebook Messenger), delivering end-to-end automation across the clinical testing workflow:

* **Omnichannel Social Automation:** Integrates Facebook Messenger (Graph API) and WhatsApp (via WAHA webhook bridge) for automated patient conversations, inquiries, and follow-ups.
* **Hybrid RAG Test Catalog Search:** Combines dense semantic vector embeddings stored in **Qdrant** with lexical / keyword searching to accurately match patient queries against thousands of medical tests and aliases.
* **AI Prescription Extraction (OCR):** Ingests prescription photos, applies computer vision and OCR extraction, identifies prescribed tests, computes costs, and submits them to laboratory doctors for validation before automated delivery to the patient.
* **Patient Booking & Reference Tracking:** Complete booking lifecycle with unique alphanumeric reference codes, patient instructions, home visit dispatch, and status transition workflows.
* **Multi-Tenant Laboratory & Subscription Engine:** Granular quotas tracking monthly AI messages, emergency grace tiers, monetary API consumption estimates, and laboratory tenant isolation.
* **Complaints & Quality Feedback:** Structured patient complaint submission with escalation status, rating collection, and instant Excel export utilities.

---

## 🏛️ Architecture & Design Pattern

### Stateful Instance-Based Object-Oriented Design
To prevent redundant database lookups and eliminate cross-layer parameter pollution, all services in `software_services/` follow an **Instance-Based Stateful OOP Pattern**:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   Stateful Service Instance Pattern                    │
├────────────────────────────────────────────────────────────────────────┤
│  Service = BookingService(booking_id=42)                               │
│                                                                        │
│  • Constructor receives identifier(s) or pre-loaded models             │
│  • @property getter lazily queries and caches the target model         │
│  • Repeated calls reuse self._cached_entity within the session         │
│  • Eliminates passing 5+ IDs through every single static call          │
└────────────────────────────────────────────────────────────────────────┘
```

#### Key Architecture Benefits:
1. **Lazy Query Caching:** Methods access `self.booking`, `self.client`, `self.subscription`, or `self.test` through properties that execute DB fetches only when required and cache the entity on the instance.
2. **Clean Separation of Concerns:** Flask routes handle HTTP parameter parsing and view rendering, while business logic, transactional integrity, and external integrations reside solely in the service layer.
3. **Zero Static Methods:** No `@staticmethod` bottlenecks; every service is unit-testable and capable of maintaining operation-specific context.
4. **Safe Backward Compatibility:** Service methods accept optional entity IDs to seamlessly support both instance-oriented and legacy call conventions without breaking existing blueprints.

---

## 🔄 System Architecture & Request Lifecycle

```
                                  EXTERNAL CHANNELS
              ┌────────────────────────────────────────────────────────┐
              │  WhatsApp (WAHA)           Facebook Messenger (Graph)  │
              │  • Patient Inquiries       • Prescription Uploads      │
              │  • Test Bookings           • Feedback & Complaints     │
              └───────────────┬────────────────────────┬───────────────┘
                              │ Webhook POST           │ Webhook POST
                              ▼                        ▼
              ┌────────────────────────────────────────────────────────┐
              │              FLASK BLUEPRINT ROUTES (`routes/`)        │
              │  • booking_routes.py         • inquiry_routes.py       │
              │  • test_routes.py            • feedback_routes.py      │
              │  • complaint_routes.py       • subscription_routes.py  │
              │  • page_routes.py            • platform_routes.py      │
              │  • laboratory_routes.py      • user_routes.py          │
              │  • login_routes.py (Dashboard & Auth)                  │
              └──────────────────────────┬─────────────────────────────┘
                                         │ Instantiates & Invokes
                                         ▼
              ┌────────────────────────────────────────────────────────┐
              │           STATEFUL SERVICES (`software_services/`)     │
              │  • BookingService            • InquiryService          │
              │  • ClientService             • TestsService            │
              │  • SubscriptionService       • FeedbackService         │
              │  • LaboratoryService         • ComplaintService        │
              │  • PageService               • DashboardService        │
              │  • PlatformService           • UserService             │
              └───────┬──────────────────┬───────────────────┬─────────┘
                      │                  │                   │
                      ▼                  ▼                   ▼
    ┌──────────────────────┐  ┌────────────────────┐  ┌────────────────────┐
    │  Relational Database │  │   Vector Engine    │  │  Vision & AI Core  │
    │  (SQLAlchemy ORM)    │  │   (Qdrant DB)      │  │  (LangChain / LLM) │
    ├──────────────────────┤  ├────────────────────┤  ├────────────────────┤
    │ • Laboratories       │  │ • 768d Embeddings  │  │ • Prescription OCR │
    │ • Tests & Prices     │  │ • Semantic Search  │  │ • Intent Router    │
    │ • Bookings & Status  │  │ • Alias Matching   │  │ • AI Text Gen      │
    │ • Chat History       │  │ • Catalog Index    │  │ • Channel Handlers │
    │ • Subscriptions      │  │                    │  │                    │
    └──────────────────────┘  └────────────────────┘  └────────────────────┘
```

---

## ⚙️ Application Core & Configuration

The application runtime is orchestrated through Flask's factory architecture and centralized environment settings:

### 📁 [app.py](app.py)
* **Type:** Application Factory & Blueprint Registry
* **Core Responsibilities:**
  * **`create_app()`:** Initializes Flask via the application factory pattern, loads configuration, initializes extensions (SQLAlchemy `db`, Flask-Migrate `migrate`, Flask-Login `login_manager`), and configures authentication entry points.
  * **`load_user()`:** User loader callback fetching active `User` instances by primary key for session management.
  * **Blueprint Registration:** Mounts all 11 application blueprints (`main_bp`, `users_bp`, `platforms_bp`, `subscription_bp`, `test_bp`, `laboratory_bp`, `bookings_bp`, `complaints_bp`, `feedbacks_bp`, `inquiries_bp`, `pages_bp`).

### 📁 [config.py](config.py)
* **Type:** Environment Configuration & Settings
* **Core Responsibilities:**
  * **`Config`:** Loads environment variables via `python-dotenv`:
    * `SQLALCHEMY_DATABASE_URI`: PyMySQL connection URI configured with `utf8mb4` encoding for full Arabic text support.
    * `SQLALCHEMY_ENGINE_OPTIONS`: Database connection pooling (`pool_recycle=280`, `pool_pre_ping=True`) ensuring socket liveness.
    * `QDRANT_URL`, `QDRANT_API_KEY`, `COLLECTION_NAME`, `VECTOR_SIZE`: Qdrant vector database parameters.
    * `GEMINI_API_KEY`, `GEMINI_MODEL`, `EMBEDDING_MODEL`: Google Gemini generation and embedding configurations.
    * `ITEMS_PER_PAGE`: Global default pagination limit for administrative dashboard views.

---

## 📦 Core Services Layer Breakdown (`software_services/`)

The following section documents all **12 stateful service classes**, their encapsulated state, and functional responsibilities:

### 📁 [booking_service.py](software_services/booking_service.py)
* **Main Class:** `BookingService`
* **Encapsulated State:** `booking_id`, `_booking`, `reference_id`
* **Methods & Responsibilities:**
  * `booking` (@property): Lazily loads and caches the `Booking` model by ID or reference.
  * `create_booking()`: Creates a booking with a unique reference, total price, and timestamps.
  * `display_bookings()`: Paginated search with status, lab, date, and keyword filters.
  * `get_booking()` / `get_booking_by_id()`: Fetches booking entity with state synchronization.
  * `get_booking_by_reference()`: Resolves booking via alphanumeric reference code.
  * `update_booking_status()`: Updates booking progress (Pending, Confirmed, Cancelled).
  * `update_booking()`: Modifies booking metadata, patient details, and prices.
  * `save_booking()`: Chatbot-friendly creation helper returning formatted Arabic confirmation.
  * `export_to_excel()`: Generates an in-memory `.xlsx` workbook of filtered bookings.

### 📁 [client_service.py](software_services/client_service.py)
* **Main Class:** `ClientService`
* **Encapsulated State:** `platform_id`, `page_id`, `sender_id`, `_client`
* **Methods & Responsibilities:**
  * `client` (@property): Lazily retrieves client model using composite credentials.
  * `get_client()`: Queries client by composite key `(platform_id, page_id, sender_id)`.
  * `get_or_create_client()`: Ensures a persistent client record exists for ongoing sessions.
  * `save_chat_exchange()`: Appends user/bot exchange to JSON chat history with sliding window limit.
  * `get_chat_history()`: Returns chronologically sorted chat history turns for prompt memory.
  * `get_last_bot_reply()`: Retrieves the most recent agent response.
  * `get_summary()`: Retrieves LLM-generated conversation summary for state tracking.

### 📁 [complaint_service.py](software_services/complaint_service.py)
* **Main Class:** `ComplaintService`
* **Encapsulated State:** `complaint_id`, `_complaint`
* **Methods & Responsibilities:**
  * `complaint` (@property): Lazily queries complaint record by ID.
  * `get_all_complaints()`: Returns paginated complaints filtered by phone, text, or status.
  * `get_complaint_details()`: Retrieves detailed complaint object.
  * `update_complaint_status()`: Updates resolution status with rollback safety.
  * `save_complaint()`: Registers new patient grievance from chatbot or web form.
  * `export_to_excel()`: Compiles complaints into styled Excel spreadsheet in memory.

### 📁 [dashboard_service.py](software_services/dashboard_service.py)
* **Main Class:** `DashboardService`
* **Encapsulated State:** `laboratory_id`
* **Methods & Responsibilities:**
  * `get_summary_data()`: Aggregates dashboard health metrics, active subscription state, message utilization percentages, and quota balances for the laboratory.

### 📁 [feedback_service.py](software_services/feedback_service.py)
* **Main Class:** `FeedbackService`
* **Encapsulated State:** `feedback_id`, `reference_id`, `_feedback`
* **Methods & Responsibilities:**
  * `feedback` (@property): Lazily loads feedback instance via ID or reference code.
  * `create_feedback()`: Persists rating scores (1-5) and reviews for completed visits.
  * `get_feedbacks()`: Paginated customer review retrieval with rating threshold filters.
  * `get_visit_by_reference()`: Validates visit eligibility using booking reference.
  * `submit_feedback()`: Validates form submission payload and rating bounds [1..5].
  * `get_feedbacks_with_stats()`: Calculates statistical aggregations (averages, totals, low scores).

### 📁 [inquiry_services.py](software_services/inquiry_services.py)
* **Main Class:** `InquiryService`
* **Encapsulated State:** `inquiry_id`, `_inquiry`
* **Methods & Responsibilities:**
  * `inquiry` (@property): Lazily loads prescription inquiry model instance.
  * `get_all_inquiries()`: Paginated inquiry log with phone and channel search.
  * `get_inquiry()` / `get_inquiry_by_id()`: Fetches single inquiry wrapped in `InquiryResult`.
  * `get_pending_count()`: Fast count query for pending doctor reviews.
  * `get_stats()`: Computes total inquiries, review status counts, and OCR confidence averages.
  * `save_inquiry()`: Persists prescription image, OCR text, confidence score, and candidate tests.
  * `update_status()`: Updates doctor review state.
  * `delete_inquiry()`: Removes inquiry record and updates cache.
  * `_build_prescription_reply()`: Builds multi-line message containing prices, sample instructions, and total.
  * `confirm_and_reply()`: Confirms tests, triggers channel handler (Facebook/WhatsApp), sends quotation, and logs exchange.

### 📁 [Laboratory_service.py](software_services/Laboratory_service.py)
* **Main Class:** `LaboratoryService`
* **Encapsulated State:** `laboratory_id`, `_lab`
* **Methods & Responsibilities:**
  * `lab` (@property): Lazily retrieves laboratory model instance.
  * `create_laboratory()`: Registers new laboratory tenant with contact details.
  * `get_laboratory()` / `get_laboratory_by_id()`: Retrieves lab profile by ID.
  * `get_all_laboratories()`: Returns all registered laboratories.
  * `update_laboratory()`: Updates lab name, address, phone number, and email.
  * `get_current_laboratory_id()`: Resolves active lab ID from session context or first record.

### 📁 [page_service.py](software_services/page_service.py)
* **Main Class:** `PageService`
* **Encapsulated State:** `platform_id`, `page_id`, `_page`
* **Methods & Responsibilities:**
  * `page` (@property): Lazily loads social page connection by composite key.
  * `get_all_platforms()`: Returns list of supported social messaging platforms.
  * `get_all_pages()`: Fetches pages with eager-loaded platform and client relationships.
  * `get_page()`: Queries specific social page channel by credentials.
  * `create_page()`: Links a social page / phone number to a laboratory with access token.
  * `update_page_token()`: Updates channel access token or webhook secret.
  * `delete_page()`: Disconnects social page and removes channel record.

### 📁 [platform_service.py](software_services/platform_service.py)
* **Main Class:** `PlatformService`
* **Encapsulated State:** `platform_id`, `_platform`
* **Methods & Responsibilities:**
  * `platform` (@property): Lazily loads platform model instance.
  * `create_platform()`: Registers new social messaging platform (e.g., 'facebook', 'whatsapp').
  * `get_platform()` / `get_platform_by_id()`: Retrieves platform by ID.
  * `update_platform()`: Modifies platform name with uniqueness validation.
  * `get_all_platforms()`: Fetches all platforms with eager-loaded pages relation.

### 📁 [subscription_service.py](software_services/subscription_service.py)
* **Main Class:** `SubscriptionService`
* **Encapsulated State:** `laboratory_id`, `_subscription`
* **Methods & Responsibilities:**
  * `subscription` (@property): Lazily retrieves active subscription for laboratory.
  * `messages_remaining()`: Returns regular monthly messages available.
  * `grace_remaining()`: Returns emergency grace quota messages remaining.
  * `usage_percentage()`: Computes percentage of message limit consumed.
  * `can_use_ai()`: Evaluates subscription status, expiration date, and quota thresholds.
  * `consume()`: Increments consumed message count and accumulates estimated dollar cost.
  * `add_estimated_cost()`: Tracks incremental model API expenditures.
  * `get_status()`: Returns UI badge status (`Active`, `Suspended`, `Expired`, `Limit Reached`).
  * `get_alert()`: Generates contextual warnings (low quota, grace mode, expiration).
  * `renew()`: Extends subscription validity by N months and resets usage.
  * `reset_usage()`: Clears message count without altering expiration date.
  * `suspend()` / `activate()`: Toggles AI bot execution authorization.
  * `update_limit()` / `update_grace_limit()`: Updates main or grace message ceilings.

### 📁 [tests_service.py](software_services/tests_service.py)
* **Main Class:** `TestsService`
* **Encapsulated State:** `test_id`, `_test`, `laboratory_id`
* **Methods & Responsibilities:**
  * `test` (@property): Lazily loads medical test model instance.
  * `get_test()` / `get_test_by_id()`: Retrieves test details by primary key ID.
  * `get_all_tests()`: Returns full laboratory test catalog.
  * `get_paginated_tests()`: Paginated test query with search by name and lab filter.
  * `create_lab_service()`: Creates test and upserts semantic vector in Qdrant.
  * `update_test()`: Updates test details, pricing, instructions, and refreshes vector index.
  * `delete_test()`: Removes test record and purges vector point from Qdrant.
  * `get_test_service_page_data()`: Gathers pagination, services list, and labs for views.
  * `handle_create_test()` / `handle_update_test()`: Form processors validating parameters and parsing aliases/keywords.
  * `process_ai_generation()` / `process_ai_regeneration()`: AI generators creating medical descriptions and preparation instructions.
  * `format_ai_response()`: Serializes AI-generated results for JSON responses.

### 📁 [User_service.py](software_services/User_service.py)
* **Main Class:** `UserService`
* **Encapsulated State:** `user_id`, `_user`
* **Methods & Responsibilities:**
  * `user` (@property): Lazily loads user model instance.
  * `get_user()` / `get_user_by_id()`: Fetches user account by ID.
  * `create_user()`: Registers new staff/admin user with Werkzeug password hashing.
  * `login_user()` / `authenticate()`: Verifies email credentials and password hash for session auth.
  * `update_user()`: Modifies user name, email, role, and optionally updates password.
  * `get_all_users()`: Returns list of all registered system users.

---

## 🌐 Routes & API Layer Breakdown (`routes/`)

The application organizes all HTTP endpoints into modular Flask Blueprints:

### 🌐 [booking_routes.py](routes/booking_routes.py)
* **Blueprint:** `bookings_bp` (`/bookings`)
* **Endpoints:**
  * `GET /bookings`: View paginated bookings list with search, status, date, and lab filters.
  * `POST /bookings/update_status/<id>`: Update booking status (Pending, Confirmed, Completed, Cancelled).
  * `GET /bookings/export`: Download in-memory Excel spreadsheet of filtered bookings.

### 🌐 [complaint_routes.py](routes/complaint_routes.py)
* **Blueprint:** `complaints_bp` (`/complaints`)
* **Endpoints:**
  * `GET /complaints`: List paginated customer complaints with status and search filter.
  * `POST /complaints/update_status/<id>`: Update complaint resolution status.
  * `GET /complaints/export`: Export filtered complaints log to an Excel `.xlsx` file.

### 🌐 [feedback_routes.py](routes/feedback_routes.py)
* **Blueprint:** `feedbacks_bp` (`/feedbacks`)
* **Endpoints:**
  * `GET /feedbacks`: View customer satisfaction dashboard, rating averages, and reviews.
  * `POST /feedback/submit`: Public API endpoint to submit ratings (1-5) and feedback by reference code.

### 🌐 [inquiry_routes.py](routes/inquiry_routes.py)
* **Blueprint:** `inquiries_bp` (`/inquiries`)
* **Endpoints:**
  * `GET /inquiries`: View prescription inquiries dashboard with OCR preview and review status.
  * `GET /inquiries/<id>`: Inspect single inquiry, OCR text, and AI-identified tests.
  * `POST /inquiries/<id>/status`: Update inquiry review state.
  * `POST /inquiries/<id>/confirm`: Doctor confirms lab tests for inquiry.

### 🌐 [laboratory_routes.py](routes/laboratory_routes.py)
* **Blueprint:** `laboratory_bp` (`/laboratories`)
* **Endpoints:**
  * `GET /laboratories`: View list of configured laboratories.
  * `GET, POST /laboratories/create`: Add new medical laboratory tenant.
  * `GET, POST /laboratories/<id>/edit`: Update laboratory profile, address, and phone numbers.

### 🌐 [login_routes.py](routes/login_routes.py)
* **Blueprint:** `main_bp` (`/`)
* **Endpoints:**
  * `GET /`: Main laboratory dashboard displaying usage metrics, active subscription, and navigation.
  * `GET, POST /login`: User authentication with remember-me support.
  * `GET /logout`: Terminate user session.

### 🌐 [page_routes.py](routes/page_routes.py)
* **Blueprint:** `pages_bp` (`/pages`)
* **Endpoints:**
  * `GET /pages`: View connected Facebook pages and WhatsApp channels with client counts.
  * `GET, POST /pages/create`: Connect new page or WhatsApp number to a laboratory.
  * `POST /pages/update-token`: Update API access token or webhook credentials.
  * `POST /pages/<plat_id>/<page_id>/delete`: Disconnect and delete social channel.

### 🌐 [platform_routes.py](routes/platform_routes.py)
* **Blueprint:** `platforms_bp` (`/platforms`)
* **Endpoints:**
  * `GET /platforms`: View supported communication platforms.
  * `GET, POST /platforms/create`: Register new platform name.
  * `GET, POST /platforms/<id>/edit`: Edit platform configuration.

### 🌐 [subscription_routes.py](routes/subscription_routes.py)
* **Blueprint:** `subscription_bp` (`/subscription`)
* **Endpoints:**
  * `GET /subscription`: View laboratory subscription status, consumed messages, and costs.
  * `POST /subscription/renew`: Renew plan by specified duration.
  * `POST /subscription/reset`: Reset message counter.
  * `POST /subscription/suspend`: Temporarily suspend AI agent operations.
  * `POST /subscription/activate`: Reactivate AI agent operations.
  * `POST /subscription/update-limit`: Modify standard message quota.
  * `POST /subscription/update-grace`: Modify emergency grace message quota.

### 🌐 [test_routes.py](routes/test_routes.py)
* **Blueprint:** `test_bp` (`/tests`)
* **Endpoints:**
  * `GET /tests`: View paginated medical test directory with lab filtering and search.
  * `POST /tests/create`: Create test, instructions, prices, and sync vector embedding.
  * `POST /tests/<id>/edit`: Update test metadata, instructions, and refresh vector index.
  * `POST /tests/<id>/delete`: Delete test and remove vector from Qdrant.
  * `POST /tests/generate-ai`: Use AI to generate test descriptions, prep instructions, and aliases.
  * `POST /tests/regenerate-ai`: Re-prompt AI for alternative medical descriptions.

### 🌐 [user_routes.py](routes/user_routes.py)
* **Blueprint:** `users_bp` (`/users`)
* **Endpoints:**
  * `GET /users`: List administrative and laboratory staff users.
  * `GET, POST /users/create`: Register new user with designated role.
  * `GET, POST /users/<id>/edit`: Update user profile and change password.

---

## 🧠 External Integrations & AI Engines (`services/` & `llm/`)

This directory houses integrations with external vector data stores, AI generation pipelines, and LLM providers:

### 📁 [llm.py](llm/llm.py)
* **Type:** LLM Client Provider Factory
* **Core Responsibilities:**
  * **`get_gemini()`:** Initializes and returns a `ChatGoogleGenerativeAI` client using `Config.GEMINI_MODEL` with `temperature=0.0` for deterministic structured schema generation.
  * **`get_gemini_embeddings()`:** Initializes and returns a `GoogleGenerativeAIEmbeddings` client using `Config.EMBEDDING_MODEL` with 768-dimensional vector outputs.

### 📁 [vector_service.py](services/vector_service.py)
* **Type:** External Engine Integration (Qdrant Vector Database)
* **Core Responsibilities:**
  * **`initialize_collection()`:** Checks if the target collection exists in Qdrant and creates it with cosine distance metrics and configured vector sizing if missing.
  * **`upsert_test_vector()`:** Generates embeddings and upserts test metadata (name, description, keywords) into the Qdrant vector database for semantic search.
  * **`delete_test_vector()`:** Removes a specific test vector point from the collection by integer ID selector.
  * **`get_test_vector()`:** Retrieves a specific test point and its associated metadata payload directly from Qdrant by primary key ID.

### 📁 [generation_service.py](services/generation_service.py)
* **Type:** AI Generation Pipeline (LLM Structured Outputs)
* **Core Responsibilities:**
  * **`_generate()`:** Enforces structured output formatting using Google Gemini and the `TestGenerationResult` Pydantic model via `.with_structured_output()`.
  * **`generate_test()`:** Prompt pipeline that takes a test name and optional initial notes to generate comprehensive descriptions (English), sample collection rules (Arabic), fasting/preparation instructions (Arabic), standard sample types, duration, and clinical aliases.
  * **`regenerate_test()`:** Prompt pipeline that takes an existing test definition and generates an alternative variation with refined phrasing, varied keywords, and updated aliases while preserving medical factuality.

---

## 🔍 Hybrid RAG Search Pipeline (`search/`)

The search pipeline combines dense semantic vector retrieval in Qdrant with sparse lexical and n-gram fuzzy matching over MySQL test records:

### 📁 [normalization.py](search/preprocess/normalization.py)
* **Type:** Text Normalization Preprocessor
* **Core Responsibilities:**
  * **`normalize()`:** Converts text to lowercase, strips non-alphanumeric punctuation using regular expressions, collapses multi-space runs, and removes leading/trailing whitespace for consistent string comparison.

### 📁 [ngram.py](search/preprocess/ngram.py)
* **Type:** Sub-word Character N-Gram Processor
* **Core Responsibilities:**
  * **`generate_ngrams()`:** Splits text into word tokens, wraps each word with boundary delimiters (`$word$`), and extracts overlapping character n-grams (default: bigrams, `n=2`).
  * **`ngram_similarity()`:** Computes the Jaccard similarity coefficient (set intersection over union) between query and candidate n-grams, delivering resilient matching against spelling typos.

### 📁 [db_queries.py](search/db_queries.py)
* **Type:** In-Memory Candidate Retrieval Layer
* **Core Responsibilities:**
  * **`_parse_json_field()`:** Robust JSON parsing helper that deserializes stringified JSON lists, raw lists, or single strings into clean `list[str]`.
  * **`get_all_active_lab_services_for_search()`:** Fetches all active `LabService` records from the database and returns structured dictionaries containing IDs, names, descriptions, parsed aliases, and keywords for in-memory lexical matching.

### 📁 [fuzzy_search.py](search/fuzzy_search.py)
* **Type:** Weighted Lexical & Fuzzy Matching Engine
* **Core Responsibilities:**
  * **`calculate_similarity()`:** Blends RapidFuzz ratio metrics (`partial_ratio` and `token_set_ratio`) with character n-gram Jaccard similarity, scaled by candidate field weights (`NAME_WEIGHT=1.0`, `ALIAS_WEIGHT=0.95`, `KEYWORD_WEIGHT=0.85`).
  * **`fuzzy_search()`:** Evaluates candidate lab services against normalized search terms, filters candidates by minimum score threshold (`MIN_SCORE=0.45`), and returns top-K ranked `SearchResult` models tagged with `source="fuzzy"`.

### 📁 [semantic_search.py](search/semantic_search.py)
* **Type:** Dense Vector Similarity Retrieval Engine
* **Core Responsibilities:**
  * **`semantic_search()`:** Builds contextual query strings, generates dense embedding vectors via Gemini, queries the Qdrant `test_services` collection, and maps vector point payloads to ranked `SearchResult` models tagged with `source="semantic"`.

### 📁 [merger.py](search/merger.py)
* **Type:** Reciprocal Fusion & Deduplication Layer
* **Core Responsibilities:**
  * **`merge_results()`:** Merges candidate results from fuzzy and semantic engines, eliminates duplicate entity IDs by retaining the maximum score, and applies a **15% reciprocal score boost** (`BOTH_SOURCES_BOOST = 1.15`, capped at 1.0) when an item is discovered by both retrieval mechanisms, labeling the source as `"fuzzy+semantic"`.

### 📁 [search_manager.py](search/search_manager.py)
* **Type:** Search Orchestrator & Context Budget Controller
* **Core Responsibilities:**
  * **`run_search()`:** Top-level search manager coordinating multi-query retrieval across fuzzy and semantic pipelines, executing result fusion, sorting candidates descending by score, and enforcing a top-50 context budget (`CONTEXT_BUDGET=50`).

---

## 🛠️ Utility Helpers & Media Generation (`utils/`)

This directory contains standalone utility functions, media renderers, text embedding processors, and search tokenizers:

### 📁 [utils.py](utils/utils.py)
* **Type:** Core Utility Helper
* **Core Responsibilities:**
  * **`create_embedding()`:** Validates that input text is non-empty and computes vector representations using LangChain's `GoogleGenerativeAIEmbeddings`.
  * **`build_test_text()`:** Combines test name, medical description, and keywords into a standardized string format (`name:... description:... keywords:...`) tailored for dense vector embedding generation.
  * **`make_reference_id()`:** Generates unique, uppercase, alphanumeric booking reference codes formatted as `BK-XXXX-YYYY` derived from UUID4.
  * **`get_platform_name()`:** Resolves numeric platform IDs (`1` -> Facebook, `2` -> WhatsApp) into human-readable messaging channel names with fallback.

### 📁 [generate_booking_img.py](utils/generate_booking_img.py)
* **Type:** Document & Image Rendering Engine
* **Core Responsibilities:**
  * **`_register_font()`:** Registers the Arabic-compatible TrueType font (`Cairo.ttf`) with ReportLab and builds glyph mappings with fallback safety.
  * **`_ar()`:** Reshapes and re-orders bidirectional Arabic text using `arabic_reshaper` and `python-bidi` for accurate canvas typesetting.
  * **`generate_booking_pdf()`:** Generates an in-memory, styled A4 PDF document containing laboratory branding, patient visit details, reference ID, and UTC timestamp.
  * **`generate_booking_img()`:** Converts the in-memory PDF confirmation into a high-resolution PNG image byte stream at configurable DPI using PyMuPDF (`fitz`), enabling direct outbound messaging over WhatsApp and Facebook.

### 📁 [embedding_utils.py](utils/embedding_utils.py)
* **Type:** Query String Formatting Utility
* **Core Responsibilities:**
  * **`build_query_text()`:** Serializes incoming patient query strings, symptom descriptions, and extracted keyword lists into a unified contextual string (`query:... description:... keywords:...`) for semantic search embeddings.

### 📁 [search_utils.py](utils/search_utils.py)
* **Type:** Search Term Preparation Utility
* **Core Responsibilities:**
  * **`prepare_search_terms()`:** Aggregates queries, alternative aliases, and keywords, strips empty values, and applies text normalization to produce clean, sanitized candidate search tokens.

---

## 📋 Data Validation & Schemas (`schemas/`)

This directory defines Pydantic schemas and structured validation models used across AI pipelines, intent routing, and search retrieval:

### 📁 [generation.py](schemas/generation.py)
* **Type:** AI Generation Schema (Pydantic)
* **Core Responsibilities:**
  * **`TestGenerationResult`:** Pydantic model defining structured laboratory test attributes produced by LLM pipelines:
    * `description` (`str`): Clear, medically accurate English description of the diagnostic test.
    * `patient_instructions` (`str`): Clear patient preparation and fasting instructions in Arabic.
    * `keywords` (`list[str]`): High-value lowercase search keywords (analytes, organs, clinical terms).
    * `alias_name` (`list[str]`): Real clinical abbreviations and Arabic/English aliases.
    * `duration` (`int`): Estimated result turnaround time in hours (defaults to `24`).
    * `sample_type` (`str`): Standard biological specimen required in Arabic (e.g., دم, سيرم, بول).
    * `instructions` (@property): Backward-compatible alias getter for `patient_instructions`.
    * `aliases` (@property): Backward-compatible alias getter for `alias_name`.

### 📁 [intent_schema.py](schemas/intent_schema.py)
* **Type:** Intent Classification & Query Disambiguation Schema (Pydantic)
* **Core Responsibilities:**
  * **`IntentType`:** Enum classifying patient inbound message intents: `VISIT` (booking appointment), `INQUIRY` (prescription inquiry), `COMPLAINT` (patient grievance), `DIRECT` (general lab query), `LABRESULTS` (viewing medical test results).
  * **`RefinedQuery`:** Pydantic model encapsulating disambiguated patient test requests:
    * `query` (`str`): Clean semantic retrieval description of the requested test.
    * `aliases` (`list[str]`): Alternative medical abbreviations or common synonyms.
    * `keywords` (`list[str]`): High-value search terms targeting clinical concepts.
    * `description` (`str`): Concise clinical summary of the test purpose.
  * **`IntentResponse`:** Top-level structured model encapsulating the resolved `intent` and a list of `refined_queries` for multi-test inquiries.

### 📁 [search_schema.py](schemas/search_schema.py)
* **Type:** Search Result Transfer Model (Pydantic)
* **Core Responsibilities:**
  * **`SearchResult`:** Lightweight transfer model representing a ranked test search match:
    * `id` (`int`): Primary key identifier of the `LabService`.
    * `name` (`str`): Official name of the laboratory service.
    * `score` (`float`): Normalized similarity confidence score [0.0..1.0].
    * `source` (`str`): Origin channel of the match (`"fuzzy"`, `"semantic"`, or `"fuzzy+semantic"`).

---

## 🤖 Prescription OCR & Doctor Validation Workflow

The automated prescription workflow ingests patient camera photos, applies visual recognition, and stages tests for clinical verification:

```
  [Patient sends photo via WhatsApp/Facebook]
                    │
                    ▼
     [Tesseract / Vision Model OCR]
     Extracts raw prescription text
                    │
                    ▼
     [AI Entity Extraction & RAG Matching]
     Identifies tests and matches prices in DB
                    │
                    ▼
     [Stored in Inquiries (Status: PENDING)]
                    │
                    ▼
     [Laboratory Doctor Reviews & Confirms Tests in UI]
                    │
                    ▼
     [Automated Reply sent via WhatsApp/Facebook Handler]
     "📋 Your prescription was reviewed by our physician.
      Total: 450 EGP. Reply 'Confirm' to book your appointment."
```

---

## 🗄️ Database Schema & Data Model (`models/`)

The relational schema is built on **SQLAlchemy ORM** ([`models/models.py`](models/models.py)) with relational foreign key integrity and cascading behaviors:

* **`Status` (Enum):** Defines lifecycle state across bookings, inquiries, and complaints (`PENDING`, `REVIEWED`, `ATTENDED`, `NO_SHOW`).
* **`User`:** System accounts for laboratory staff and administrators with hashed passwords and authentication session integration.
* **`Laboratory`:** Multi-tenant diagnostic laboratory accounts containing business name, address, contact information, and relational child associations.
* **`LabService`:** Medical test catalog items containing price, estimated duration, Arabic patient preparation instructions, clinical descriptions, JSON-serialized aliases, JSON keywords, and biological sample types.
* **`Platform`:** Supported external messaging channels (`Facebook`, `WhatsApp`).
* **`Page`:** Composite primary key `(page_id, platform_id)` linking social messaging pages and WhatsApp accounts to laboratories with access tokens.
* **`Client`:** Composite primary key `(sender_id, page_id, platform_id)` maintaining conversational state, sliding-window chat history (last 7 exchanges), and summarized context.
* **`Booking`:** Patient reservations featuring unique alphanumeric reference codes (`reference_id`), patient identity, appointment schedule, requested test names, address, and status.
* **`Inquiry`:** Prescription photo submissions storing image URI, OCR extracted text, recognition confidence score, candidate test selections, and doctor verification timestamps.
* **`Complaint`:** Customer grievances recording communication channel, sender contact, complaint text, and resolution status.
* **`Subscription`:** Multi-tenant quota tracker managing plan name, regular message allocations, grace allowances, consumed message volume, accumulated API costs, and renewal cycles.
* **`Feedback`:** Customer satisfaction reviews with 1-to-5 star ratings for overall experience and ease-of-use, linked directly to visit reference codes.

---

## 🧪 Bulk Ingestion & Verification Tools

### 📁 [import_excel_knowledge.py](import_excel_knowledge.py)
* **Type:** Automated Catalog Ingestion CLI
* **Core Responsibilities:**
  * **Excel Processing:** Ingests rows from `Filtered_Tests_Prices.xlsx` containing medical test names, categories, and pricing.
  * **AI Pipeline Orchestration:** Automatically calls `generate_test()` for each test to synthesize descriptions, Arabic fasting instructions, sample types, duration, aliases, and keywords.
  * **Dual Persistence:** Inserts records into the MySQL `LabService` table and upserts dense embeddings into Qdrant via `TestsService.create_lab_service()`.
  * **Fault-Tolerant Execution:** Supports automatic resume (skips existing tests), dry-run testing (`--dry-run`), vector upsert bypass (`--skip-vectors`), rate-limiting delays (`--sleep`), and failure auditing in `failed_tests.csv`.

### 📁 [test_rag.py](test_rag.py)
* **Type:** Search Benchmarking & Quality Verification Testbed
* **Core Responsibilities:**
  * **Comprehensive Test Suite:** Evaluates the hybrid RAG pipeline across **35 diverse test scenarios**:
    * Direct clinical test names (e.g., "CBC", "Lipid Profile", "TSH").
    * Colloquial Arabic terms and phonetics (e.g., "سي بي سي", "تحليل الكبد").
    * Intentional spelling typos (e.g., "CBS", "Vitmin D", "creatinin test").
    * Symptomatic queries lacking explicit test names (e.g., "عايز أعرف لو عندي أنيميا", "عندي عطش زيادة ونزول وزن").
    * Edge cases (empty queries, nonexistent tests, keyword-only inputs).
  * **Quality Scoring:** Validates reciprocal score fusion, confidence thresholds (`--min-score`), and source attribution.

---

## 🚀 Setup & Execution Guide

### Prerequisites
* Python 3.10+
* MySQL Server (configured with `utf8mb4` encoding)
* Qdrant instance (local container or Qdrant Cloud)
* Google Gemini API Key

### Installation
1. **Clone the Repository:**
   ```bash
   git clone https://github.com/mohamedAhmed-danger/Elsadara-agent.git
   cd Elsadara-agent
   ```

2. **Create and Activate a Virtual Environment:**
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate
   ```

3. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables (`.env`):**
   ```env
   SECRET_KEY=your_secret_key_here
   MYSQL_USER=your_db_user
   MYSQL_PASSWORD=your_db_password
   MYSQL_HOST=localhost
   MYSQL_PORT=3306
   MYSQL_DB=elsadara_db
   # Optional full URI:
   # DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/elsadara_db?charset=utf8mb4

   QDRANT_URL=http://localhost:6333
   QDRANT_API_KEY=your_qdrant_api_key
   VECTOR_SIZE=768
   COLLECTION_NAME=test_services

   GEMINI_API_KEY=your_gemini_api_key
   GEMINI_MODEL=gemini-1.5-flash
   EMBEDDING_MODEL=models/text-embedding-004
   ITEMS_PER_PAGE=10
   ```

5. **Initialize Database Migrations:**
   ```bash
   flask db upgrade
   ```

6. **Run the Development Server:**
   ```bash
   python app.py
   ```
   Access the dashboard at `http://localhost:5000`.

---

## 🛡️ Quality & Verification

* All 12 services in `software_services/` adhere to the stateful instance-based pattern with zero remaining `@staticmethod` calls.
* Database models feature lazy query caching and session rollback safety across all transactional write methods.
* Multi-channel messaging (Facebook Messenger & WhatsApp) cleanly isolates tenant laboratory quotas and conversation history.
* The Hybrid RAG engine rigorously combines semantic vector proximity with RapidFuzz lexical matching and n-gram typo correction.
#   e l r a s h e d - l a b s  
 