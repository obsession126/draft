"""In-memory telemetry pipeline and bounded history for the dashboard API."""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from analytics.contracts import ANALYSIS_VERSION, FEATURE_NAMES, SCHEMA_VERSION
from analytics.detector import NonlinearAnomalyDetector
from analytics.simulator import TelemetrySimulator


class AnalyticsEngine:
    def __init__(
        self,
        *,
        seed: int = 42,
        scenario: str = "demo",
        interval_seconds: float = 1.0,
        calibration_samples: int = 768,
        history_limit: int = 500,
        profile_id: str = "crew-01",
        start_index: int = 0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero.")
        if history_limit <= 0:
            raise ValueError("history_limit must be greater than zero.")
        if start_index < 0:
            raise ValueError("start_index must not be negative.")

        self.scenario = scenario
        self.interval_seconds = interval_seconds
        self.calibration_samples = calibration_samples
        self._simulator = TelemetrySimulator(seed=seed, profile_id=profile_id)
        self._detector = NonlinearAnomalyDetector(seed=seed)
        calibration_simulator = TelemetrySimulator(seed=seed + 1)
        calibration = [
            calibration_simulator.generate_normal_vector(index)
            for index in range(calibration_samples)
        ]
        self._detector.fit(calibration)
        self._history: deque[dict[str, Any]] = deque(maxlen=history_limit)
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._sample_index = start_index
        self._started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._collect,
            name="synthetic-telemetry",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval_seconds + 1.0))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            latest = self._history[-1] if self._history else None
            return {
                "schema_version": SCHEMA_VERSION,
                "service": self._service_status(),
                "event_count": self._sample_index,
                "latest": latest,
            }

    def history(self, limit: int = 100) -> dict[str, Any]:
        safe_limit = min(max(limit, 1), 500)
        with self._lock:
            items = list(self._history)[-safe_limit:]
            return {
                "schema_version": SCHEMA_VERSION,
                "items": items,
                "count": len(items),
                "event_count": self._sample_index,
            }

    def wait_for_event(self, after_event_id: str | None, timeout: float = 15.0) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                history = list(self._history)
                if history:
                    if after_event_id is None:
                        return history[-1]
                    for index, event in enumerate(history):
                        if event["event_id"] == after_event_id:
                            if index + 1 < len(history):
                                return history[index + 1]
                            break
                    else:
                        return history[0]
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(timeout=remaining)

    def _service_status(self) -> dict[str, Any]:
        return {
            "status": "running" if self._thread and self._thread.is_alive() else "stopped",
            "source": "synthetic-simulator",
            "scenario_mode": self.scenario,
            "analysis_version": ANALYSIS_VERSION,
            "calibration": {
                "source": "synthetic-normal-baseline",
                "samples": self.calibration_samples,
                "medical_validation": False,
            },
            "started_at": self._started_at,
        }

    def _collect(self) -> None:
        while not self._stop_event.is_set():
            index = self._sample_index
            raw_event = self._simulator.generate(index, self.scenario)
            event = self._analyze(raw_event)
            with self._condition:
                self._history.append(event)
                self._sample_index += 1
                self._condition.notify_all()
            self._stop_event.wait(self.interval_seconds)

    def _analyze(self, raw_event: dict[str, Any]) -> dict[str, Any]:
        measurements = raw_event["measurements"]
        features = {
            name: measurements[name]["value"]
            for name in FEATURE_NAMES
        }
        quality = {
            name: measurements[name]["quality"]
            for name in FEATURE_NAMES
        }
        detection = self._detector.analyze(features, quality)
        return {
            **raw_event,
            "analysis": detection.to_dict(),
        }
