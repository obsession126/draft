"""Start the synthetic telemetry and analytics service."""

from __future__ import annotations

import argparse
import logging

from analytics.engine import AnalyticsEngine
from analytics.server import AnalyticsHTTPServer, allowed_origins_from_environment
from analytics.simulator import SUPPORTED_SCENARIOS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the synthetic astronaut telemetry and anomaly-analysis demo."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: localhost only).")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port (default: 8765).")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between samples.")
    parser.add_argument("--seed", type=int, default=42, help="Repeatable simulation seed.")
    parser.add_argument(
        "--scenario",
        choices=SUPPORTED_SCENARIOS,
        default="demo",
        help="Scenario mode; demo cycles through baseline and scripted signal cases.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    engine = AnalyticsEngine(
        seed=args.seed,
        scenario=args.scenario,
        interval_seconds=args.interval,
    )
    server = AnalyticsHTTPServer(
        (args.host, args.port),
        engine,
        allowed_origins=allowed_origins_from_environment(),
    )
    engine.start()
    logging.info("Analytics API listening at http://%s:%s", args.host, args.port)
    logging.info("Dashboard stream: http://%s:%s/api/v1/stream", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Stopping analytics service.")
    finally:
        server.shutdown()
        server.server_close()
        engine.stop()


if __name__ == "__main__":
    main()
