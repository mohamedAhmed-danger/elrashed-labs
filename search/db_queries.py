import json
import logging
from typing import Any

from models.models import LabService, db

logger = logging.getLogger(__name__)


def _parse_json_field(value: Any) -> list[str]:
    """Convert a JSON list field into a clean list of strings."""

    if not value:
        return []

    if isinstance(value, list):
        return [
            str(item).strip()
            for item in value
            if item
        ]

    if isinstance(value, str):
        try:
            parsed = json.loads(value)

            if isinstance(parsed, list):
                return [
                    str(item).strip()
                    for item in parsed
                    if item
                ]

        except (json.JSONDecodeError, TypeError):
            return [value.strip()]

    return []


def get_all_active_lab_services_for_search() -> list[dict]:
    """Load lab services and prepare fields needed by the search pipeline."""

    services = []

    try:
        lab_services = db.session.query(LabService).all()

        for service in lab_services:
            services.append(
                {
                    "id": service.id,
                    "name": service.name,
                    "description": service.description or "",
                    "aliases": _parse_json_field(
                        service.alias_name
                    ),
                    "keywords": _parse_json_field(
                        service.keywords
                    ),
                }
            )

    except Exception as exc:
        logger.exception(
            "Error fetching lab services for search: %s",
            exc,
        )

    return services


def get_lab_services_by_ids(
    ids: list,
) -> list[LabService]:
    """Load complete lab service records by their IDs."""

    if not ids:
        return []

    clean_ids = [
        int(item)
        for item in ids
        if str(item).isdigit()
    ]

    if not clean_ids:
        return []

    try:
        return (
            LabService.query
            .filter(
                LabService.id.in_(clean_ids)
            )
            .all()
        )

    except Exception:
        logger.exception(
            "Error fetching lab services by IDs: %s",
            clean_ids,
        )
        raise