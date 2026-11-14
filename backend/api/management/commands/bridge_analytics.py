import json
import logging
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand, CommandError

LOGGER = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Forward the analytics service's SSE telemetry into this DRF backend."

    def add_arguments(self, parser):
        parser.add_argument("--analytics-url", default="http://127.0.0.1:8765/api/v1/stream")
        parser.add_argument("--backend-url", default="http://127.0.0.1:8000/api/v1/telemetry/ingest/")
        parser.add_argument("--token", required=True, help="DRF API token for the profile owner.")
        parser.add_argument("--last-event-id", default="")

    def handle(self, *args, **options):
        last_event_id = options["last_event_id"]
        retry_delay = 1
        self.stdout.write("Starting analytics-to-DRF bridge. Press Ctrl+C to stop.")
        while True:
            request = Request(
                options["analytics_url"],
                headers={
                    "Accept": "text/event-stream",
                    **({"Last-Event-ID": last_event_id} if last_event_id else {}),
                },
            )
            try:
                with urlopen(request, timeout=60) as stream:
                    retry_delay = 1
                    current_id = ""
                    data_lines = []
                    for raw_line in stream:
                        line = raw_line.decode("utf-8").rstrip("\r\n")
                        if line.startswith("id:"):
                            current_id = line[3:].strip()
                        elif line.startswith("data:"):
                            data_lines.append(line[5:].lstrip())
                        elif not line and data_lines:
                            event = self._decode_event(data_lines)
                            self._forward_event(
                                options["backend_url"],
                                options["token"],
                                event,
                            )
                            last_event_id = current_id or event["event_id"]
                            self.stdout.write(
                                f"{last_event_id}: {event['analysis']['status']}"
                            )
                            current_id = ""
                            data_lines = []
                raise URLError("Analytics event stream closed.")
            except HTTPError as exc:
                details = exc.read().decode("utf-8", errors="replace")
                raise CommandError(
                    f"Analytics bridge received HTTP {exc.code}: {details[:500]}"
                ) from exc
            except (URLError, TimeoutError, ConnectionError) as exc:
                LOGGER.warning("Analytics bridge disconnected: %s", exc)
                self.stderr.write(
                    f"Connection interrupted; reconnecting in {retry_delay}s."
                )
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)

    @staticmethod
    def _decode_event(data_lines):
        try:
            event = json.loads("\n".join(data_lines))
        except json.JSONDecodeError as exc:
            raise CommandError("Analytics SSE contained invalid JSON.") from exc
        if not isinstance(event, dict) or not isinstance(event.get("event_id"), str):
            raise CommandError("Analytics SSE event is missing its event_id.")
        return event

    @staticmethod
    def _forward_event(backend_url, token, event):
        body = json.dumps(
            {"event": event},
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        request = Request(
            backend_url,
            data=body,
            headers={
                "Authorization": f"Token {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        retry_delay = 1
        while True:
            try:
                with urlopen(request, timeout=15) as response:
                    result = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                details = exc.read().decode("utf-8", errors="replace")
                if 500 <= exc.code < 600:
                    LOGGER.warning(
                        "Backend returned HTTP %s for %s; retrying in %ss.",
                        exc.code,
                        event["event_id"],
                        retry_delay,
                    )
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 30)
                    continue
                raise CommandError(
                    f"Backend rejected event {event['event_id']} with HTTP "
                    f"{exc.code}: {details[:500]}"
                ) from exc
            except (URLError, TimeoutError, ConnectionError) as exc:
                LOGGER.warning(
                    "Could not deliver event %s: %s; retrying in %ss.",
                    event["event_id"],
                    exc,
                    retry_delay,
                )
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)
        if result.get("event_id") != event["event_id"]:
            raise CommandError(
                f"Backend acknowledgement did not match event {event['event_id']}."
            )
