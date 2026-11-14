import json
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from jsonschema import Draft202012Validator, FormatChecker


@lru_cache(maxsize=1)
def telemetry_event_validator():
    schema_path = settings.BASE_DIR.parent / "analytics" / "event.schema.json"
    with schema_path.open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_telemetry_event(event):
    return sorted(
        telemetry_event_validator().iter_errors(event),
        key=lambda error: list(str(part) for part in error.absolute_path),
    )
