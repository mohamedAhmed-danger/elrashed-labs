# Platform Architecture & Redis Queue Worker

## Overview
The application uses a Redis-backed distributed queue to handle message debouncing and agent execution across multi-worker deployment environments (e.g. Gunicorn / Docker).

## Redis Queue Architecture
- **Webhooks (`services/messaging/webhook_service.py`)**:
  - Inbound messages pass through `handler.prepare(message)` for media download, OCR, and billing deductions.
  - Text and OCR-processed agent payloads are pushed to Redis via `enqueue_message()` into `queue:{platform_id}:{page_id}:{sender_id}` and scheduled in the `conversations:due` Sorted Set.
- **Worker (`services/messaging/redis_worker.py`)**:
  - Must run as a separate, standing background process:
    ```bash
    python -m services.messaging.redis_worker
    ```
  - Processes due conversation queues, concatenates debounced text entries, invokes `run_agent()`, sends replies, and manages atomic recovery of stale processing claims via Lua scripts.
