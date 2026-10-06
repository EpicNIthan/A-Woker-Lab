from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Iterable

from .contracts import FlowObservation, utc_now_ms
from .engine_v1_1 import CapitalFlowEngineV11
from .evidence_health import build_evidence_health
from .handoff import build_anata_handoff
from .output import CapitalFlowOutputBuilder
from .providers import DefiLlamaStablecoinCollector, FarsideEtfCollector, JsonlFlowAdapter
from .providers_abtc import AmericanBitcoinTreasuryCollector
from .providers_free import KoteFreeCollector
from .providers_ibit import IbitHoldingsCollector
from .providers_bitmex import BitmexReserveCollector
from .providers_circle import CircleUsdcCirculationCollector
from .providers_mempool import MempoolMinerNetworkCollector
from .providers_strategy import StrategyTreasuryCollector
from .providers_kote_active import ActivatedKoteCollector
from .providers_v1 import DefiLlamaStablecoinCompositionCollector, GlassnodePitCollector
from .storage import append_observations, atomic_write_json, load_observations

DEFAULT_LOCAL_DIR = Path(".local") / "capital_flow"


def _attempt(name: str, now: int, *, status: str, count: int = 0, errors: int = 0, mode: str = "network") -> dict:
    return {"collector": name, "status": status, "attempted_at_ms": int(now), "observation_count": int(count), "error_count": int(errors), "mode": mode}


def _collect_live(*, observed_at_ms: int, include_backfill: bool) -> tuple[list[FlowObservation], list[str], list[dict]]:
    observations: list[FlowObservation] = []
    errors: list[str] = []
    attempts: list[dict] = []
    collectors = (
        ("farside_etf", FarsideEtfCollector(), {"include_backfill": include_backfill}),
        ("ishares_ibit_holdings", IbitHoldingsCollector(), {}),
        ("bitmex_reserve_transparency", BitmexReserveCollector(), {}),
        ("mempool_miner_network", MempoolMinerNetworkCollector(), {}),
        ("strategy_treasury", StrategyTreasuryCollector(), {}),
        ("american_bitcoin_treasury", AmericanBitcoinTreasuryCollector(), {}),
        ("defillama_stablecoin", DefiLlamaStablecoinCollector(), {"include_backfill": include_backfill}),
        ("defillama_stablecoin_components", DefiLlamaStablecoinCompositionCollector(), {}),
        ("circle_usdc_circulation", CircleUsdcCirculationCollector(), {}),
    )
    for name, collector, extra in collectors:
        try:
            rows = list(collector.collect(observed_at_ms=observed_at_ms, **extra))
            observations.extend(rows)
            attempts.append(_attempt(name, observed_at_ms, status="OK", count=len(rows)))
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            attempts.append(_attempt(name, observed_at_ms, status="FAILED", errors=1))
    return observations, errors, attempts


def _scoring_history(observations: Iterable[FlowObservation]) -> list[FlowObservation]:
    return [obs for obs in observations if not bool(dict(obs.provenance).get("context_only", False))]


def run_once(
    *,
    local_dir: str | Path = DEFAULT_LOCAL_DIR,
    external_jsonl: Iterable[str | Path] = (),
    glassnode_config: str | Path | None = None,
    glassnode_api_key_env: str = "GLASSNODE_API_KEY",
    kote_enabled: bool = False,
    kote_api_key_env: str = "KOTE_API_KEY",
    network: bool = True,
    include_backfill: bool = False,
    as_of_ms: int | None = None,
) -> dict:
    now = utc_now_ms() if as_of_ms is None else int(as_of_ms)
    local = Path(local_dir)
    archive_path = local / "observations.jsonl"
    collected: list[FlowObservation] = []
    source_errors: list[str] = []
    collection_attempts: list[dict] = []

    if network:
        live, errors, attempts = _collect_live(observed_at_ms=now, include_backfill=include_backfill)
        collected.extend(live)
        source_errors.extend(errors)
        collection_attempts.extend(attempts)

        if kote_enabled:
            try:
                kote = ActivatedKoteCollector.from_env(api_key_env=kote_api_key_env)
                rows, kote_errors = kote.collect_with_errors(observed_at_ms=now, include_backfill=include_backfill)
                rows = list(rows)
                collected.extend(rows)
                source_errors.extend(kote_errors)
                collection_attempts.append(_attempt("kote", now, status="PARTIAL" if kote_errors else "OK", count=len(rows), errors=len(kote_errors)))
            except Exception as exc:
                source_errors.append(f"kote: {type(exc).__name__}: {exc}")
                collection_attempts.append(_attempt("kote", now, status="FAILED", errors=1))

        if glassnode_config is not None:
            try:
                collector = GlassnodePitCollector.from_config_file(glassnode_config, api_key_env=glassnode_api_key_env)
                rows = list(collector.collect(observed_at_ms=now, include_backfill=include_backfill))
                collected.extend(rows)
                collection_attempts.append(_attempt("glassnode_pit", now, status="OK", count=len(rows)))
            except Exception as exc:
                source_errors.append(f"glassnode_pit: {type(exc).__name__}: {exc}")
                collection_attempts.append(_attempt("glassnode_pit", now, status="FAILED", errors=1))

    for path in external_jsonl:
        name = f"external_jsonl:{path}"
        try:
            rows = list(JsonlFlowAdapter(path).collect())
            collected.extend(rows)
            collection_attempts.append(_attempt(name, now, status="OK", count=len(rows), mode="local"))
        except Exception as exc:
            source_errors.append(f"{name}: {type(exc).__name__}: {exc}")
            collection_attempts.append(_attempt(name, now, status="FAILED", errors=1, mode="local"))

    appended = append_observations(archive_path, collected)
    history = load_observations(archive_path, max_records=100_000)
    scoring_history = _scoring_history(history)
    frame = CapitalFlowEngineV11().build(scoring_history, as_of_ms=now)
    frame_audit = frame.to_audit_dict()
    frame_audit["source_errors"] = list(source_errors)
    frame_audit["collection_attempts"] = list(collection_attempts)
    frame_audit["context_only_observation_count"] = len(history) - len(scoring_history)
    frame_audit["engine_variant"] = "capital-flow-v1.1-cadence-aware-freshness"
    frame_audit["kote_enabled"] = bool(kote_enabled)

    output = CapitalFlowOutputBuilder().build(frame)
    compact = output.to_dict()
    if source_errors:
        compact["audit_flags"] = list(dict.fromkeys(compact["audit_flags"] + ["SOURCE_COLLECTION_ERRORS_PRESENT"]))

    anata_handoff = build_anata_handoff(frame, history, source_errors=source_errors)
    anata_handoff["evidence_health"] = build_evidence_health(history, as_of_ms=now, source_errors=source_errors, collection_attempts=collection_attempts)

    latest_path = local / "latest.json"
    audit_path = local / "audit_latest.json"
    anata_path = local / "anata_latest.json"
    atomic_write_json(latest_path, compact)
    atomic_write_json(audit_path, frame_audit)
    atomic_write_json(anata_path, anata_handoff)
    return {
        "output": compact,
        "anata_output": anata_handoff,
        "source_errors": source_errors,
        "collection_attempts": collection_attempts,
        "appended_observations": appended,
        "archive_records_loaded": len(history),
        "scoring_records_loaded": len(scoring_history),
        "kote_enabled": bool(kote_enabled),
        "paths": {"archive": str(archive_path), "latest": str(latest_path), "audit_latest": str(audit_path), "anata_latest": str(anata_path)},
    }


def run_kote_probe(*, local_dir: str | Path = DEFAULT_LOCAL_DIR, api_key_env: str = "KOTE_API_KEY") -> dict:
    local = Path(local_dir)
    probe_path = local / "kote_probe.json"
    collector = KoteFreeCollector.from_env(api_key_env=api_key_env)
    probe = collector.probe()
    probe["path"] = str(probe_path)
    probe["has_errors"] = any(bool(item.get("error")) for item in probe.get("charts", []))
    atomic_write_json(probe_path, probe)
    return probe


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic Capital Flow V1.1 once.")
    parser.add_argument("--local-dir", default=str(DEFAULT_LOCAL_DIR))
    parser.add_argument("--external-jsonl", action="append", default=[], help="Optional point-in-time-safe provider JSONL. May be repeated.")
    parser.add_argument("--glassnode-config", default=None, help="Optional JSON config for approved Glassnode metrics. Every metric is rejected unless Glassnode metadata declares is_pit=true.")
    parser.add_argument("--glassnode-api-key-env", default="GLASSNODE_API_KEY", help="Environment variable containing the Glassnode API key.")
    parser.add_argument("--kote", action="store_true", help="Enable the schema-locked free Kote Exchange/LTH/Miner source. Requires a free API key in --kote-api-key-env.")
    parser.add_argument("--kote-probe", action="store_true", help="Probe the free Kote API schemas only. This does not append observations or change Capital Flow scoring.")
    parser.add_argument("--kote-api-key-env", default="KOTE_API_KEY", help="Environment variable containing the free Kote API key.")
    parser.add_argument("--no-network", action="store_true", help="Use only the local archive/external JSONL.")
    parser.add_argument("--include-backfill", action="store_true", help="Bootstrap provider history as first-known at this collection time. Those rows may support current/future states but never pre-bootstrap replay.")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.kote_probe:
        try:
            result = run_kote_probe(local_dir=args.local_dir, api_key_env=args.kote_api_key_env)
        except Exception as exc:
            result = {"provider": "Kote Charts", "probe_only": True, "api_key_included": False, "error": f"{type(exc).__name__}: {exc}"}
            print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
            return 2
        print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
        return 0

    result = run_once(local_dir=args.local_dir, external_jsonl=args.external_jsonl, glassnode_config=args.glassnode_config, glassnode_api_key_env=args.glassnode_api_key_env, kote_enabled=args.kote, kote_api_key_env=args.kote_api_key_env, network=not args.no_network, include_backfill=args.include_backfill)
    if args.pretty:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(json.dumps(result["anata_output"], sort_keys=True))
        if result["source_errors"]:
            print("Capital Flow source warnings:", file=sys.stderr)
            for error in result["source_errors"]:
                print(f"- {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
