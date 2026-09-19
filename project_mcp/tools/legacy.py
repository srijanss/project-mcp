"""Spec-named legacy signal tool wrappers — get_legacy_hotspots, get_legacy_signals."""

import json
from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import ensure_fresh_index


def _signal_row_to_dict(row: tuple) -> dict:
    target, signal, severity, confidence, evidence = row
    return {
        "target": target,
        "signal": signal,
        "severity": severity,
        "confidence": confidence,
        "evidence": evidence,
    }


def _decode_evidence(evidence: str | None) -> list:
    if not evidence:
        return []
    try:
        return json.loads(evidence)
    except json.JSONDecodeError:
        return []


def _ensure_indexed_connection(project_root: Path):
    project_root = Path(project_root)
    config = load_config(project_root)
    conn = get_connection(project_root)
    ensure_fresh_index(conn, project_root, config)
    return conn


def get_legacy_signals(project_root: Path, target: str) -> list[dict]:
    """Evidence-backed legacy signals for a single target (no verdict language)."""
    conn = _ensure_indexed_connection(project_root)

    rows = conn.execute(
        "SELECT target, signal, severity, confidence, evidence"
        " FROM legacy_signals WHERE target = ?",
        (target,),
    ).fetchall()

    signals = []
    for row in rows:
        signal = _signal_row_to_dict(row)
        signal.pop("target")
        signal["evidence"] = _decode_evidence(signal["evidence"])
        signals.append(signal)
    return signals


def get_legacy_hotspots(project_root: Path, limit: int = 20) -> list[dict]:
    """Targets ranked by number of evidence-backed legacy signals (no verdict language)."""
    conn = _ensure_indexed_connection(project_root)

    rows = conn.execute(
        "SELECT target, signal, severity, confidence, evidence FROM legacy_signals"
    ).fetchall()

    by_target: dict[str, list[dict]] = {}
    for target, signal, severity, confidence, evidence in rows:
        by_target.setdefault(target, []).append(
            {
                "signal": signal,
                "severity": severity,
                "confidence": confidence,
                "evidence": _decode_evidence(evidence),
            }
        )

    hotspots = [
        {"target": target, "signal_count": len(signals), "signals": signals}
        for target, signals in by_target.items()
    ]
    hotspots.sort(key=lambda h: h["signal_count"], reverse=True)
    return hotspots[:limit]
