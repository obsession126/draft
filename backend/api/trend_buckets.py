import math
from collections import Counter

from analytics.contracts import FEATURES


def aggregate_event_payload(payload):
    measurements = payload["measurements"]
    stats = {
        "event_count": 1,
        "metrics": {},
        "context_stats": {},
        "analysis_status_counts": Counter({payload["analysis"]["status"]: 1}),
        "source_counts": Counter({payload.get("source", "unknown"): 1}),
        "synthetic_event_count": int(payload.get("is_synthetic") is True),
    }

    for feature in FEATURES:
        measurement = measurements[feature.name]
        quality = measurement["quality"]
        metric = {
            "good_count": 0,
            "low_count": 0,
            "missing_count": 0,
            "sum": 0.0,
            "min": None,
            "max": None,
            "category_counts": Counter(),
        }
        value = measurement["value"]
        if quality == "good" and _is_finite_number(value):
            metric["good_count"] = 1
            if feature.unit == "category_code":
                metric["category_counts"][str(int(value))] = 1
            else:
                metric["sum"] = float(value)
                metric["min"] = float(value)
                metric["max"] = float(value)
        elif quality == "low":
            metric["low_count"] = 1
        else:
            metric["missing_count"] = 1
        stats["metrics"][feature.name] = metric

    context = payload.get("context", {})
    context_stats = stats["context_stats"]
    for name in ("mission_elapsed_min",):
        value = context.get(name)
        if _is_finite_number(value):
            context_stats[name] = {"sum": float(value), "count": 1}
    for name in ("eva_active", "link_online"):
        value = context.get(name)
        if isinstance(value, bool):
            context_stats[name] = {"true_count": int(value), "false_count": int(not value)}
    for name in ("activity_intensity_0_1", "radiation_dose_rate_usv_h"):
        measurement = measurements[name]
        value = measurement["value"]
        if measurement["quality"] == "good" and _is_finite_number(value):
            context_stats[name] = {"sum": float(value), "count": 1}

    return stats


def merge_aggregate_stats(target, incoming):
    target["event_count"] += incoming["event_count"]
    target["synthetic_event_count"] += incoming["synthetic_event_count"]
    _merge_counts(target["analysis_status_counts"], incoming["analysis_status_counts"])
    _merge_counts(target["source_counts"], incoming["source_counts"])

    for name, new_metric in incoming["metrics"].items():
        metric = target["metrics"].setdefault(
            name,
            {
                "good_count": 0,
                "low_count": 0,
                "missing_count": 0,
                "sum": 0.0,
                "min": None,
                "max": None,
                "category_counts": {},
            },
        )
        metric["good_count"] += new_metric["good_count"]
        metric["low_count"] += new_metric["low_count"]
        metric["missing_count"] += new_metric["missing_count"]
        metric["sum"] += new_metric["sum"]
        if new_metric["min"] is not None:
            metric["min"] = (
                new_metric["min"]
                if metric["min"] is None
                else min(metric["min"], new_metric["min"])
            )
            metric["max"] = (
                new_metric["max"]
                if metric["max"] is None
                else max(metric["max"], new_metric["max"])
            )
        _merge_counts(metric["category_counts"], new_metric["category_counts"])

    for name, new_value in incoming["context_stats"].items():
        current = target["context_stats"].setdefault(
            name,
            {key: 0.0 for key in new_value},
        )
        for key, value in new_value.items():
            current[key] += value


def metric_value(metric, unit):
    if not metric or metric["good_count"] == 0:
        return None
    if unit == "category_code":
        return float(
            max(
                metric["category_counts"].items(),
                key=lambda item: (item[1], item[0]),
            )[0]
        )
    return float(metric["sum"]) / metric["good_count"]


def model_context(context_stats):
    context = {}
    elapsed = context_stats.get("mission_elapsed_min")
    if elapsed and elapsed["count"]:
        context["mission_elapsed_min"] = elapsed["sum"] / elapsed["count"]
    for name in ("eva_active", "link_online"):
        counts = context_stats.get(name)
        if counts and counts["true_count"] + counts["false_count"]:
            context[name] = counts["true_count"] >= counts["false_count"]
    context["measurements"] = {}
    for name in ("activity_intensity_0_1", "radiation_dose_rate_usv_h"):
        summary = context_stats.get(name)
        context["measurements"][name] = {
            "value": summary["sum"] / summary["count"] if summary and summary["count"] else None,
            "quality": "good" if summary and summary["count"] else "missing",
        }
    return context


def _merge_counts(target, incoming):
    for key, value in incoming.items():
        target[key] = target.get(key, 0) + value


def _is_finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )
