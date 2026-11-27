"""Smoke test: broker email -> extractor -> underwriting -> RAG -> decision."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

UNDERWRITING_URL = os.getenv("UNDERWRITING_URL", "http://underwriting-agent:8002")
EXTRACTOR_URL = os.getenv("EXTRACTOR_URL", "http://submission-extractor:8000")
KNOWLEDGE_URL = os.getenv("KNOWLEDGE_URL", "http://knowledge-agent:8001")
ANALYST_URL = os.getenv("ANALYST_URL", "http://data-analyst-agent:8003")
INTAKE_URL = os.getenv("INTAKE_URL", "http://email-intake:8004")
SAMPLES_DIR = Path(os.getenv("SAMPLES_DIR", "/samples"))
OUTPUT_DIR = Path(os.getenv("SMOKE_OUT", "/out"))


@dataclass(frozen=True)
class Case:
    label: str
    filename: str
    expected: str
    overrides: dict[str, Any] = field(default_factory=dict)
    persist: bool = False
    expected_decision: str | None = None


CYBER = {
    "mfa_enabled": True,
    "requested_limit_cad": 1_000_000,
    "requested_retention_cad": 10_000,
    "handles_personal_data": True,
    "handles_payment_card_data": False,
    "endpoint_detection_response": True,
    "offline_backups": True,
}


CASES = [
    Case("cyber - champs manquants", "cyber_submission.txt", "PENDING_INFORMATION"),
    Case(
        "cyber - complete par overrides",
        "cyber_submission.txt",
        "EVALUATED",
        overrides=CYBER,
        persist=True,
        expected_decision="ACCEPT",
    ),
    Case("incomplet", "incomplete_submission.txt", "PENDING_INFORMATION"),
    Case("hors perimetre", "restaurant_submission.txt", "UNSUPPORTED_SUBMISSION"),
    Case(
        "cyber - limite hors autorite (RAG)",
        "cyber_submission.txt",
        "EVALUATED",
        overrides={**CYBER, "requested_limit_cad": 3_000_000},
        persist=True,
        expected_decision="REFER",
    ),
]


def http_json(method, url, payload=None, timeout=120.0):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as err:
        raw = err.read().decode()
        try:
            return err.code, json.loads(raw)
        except json.JSONDecodeError:
            return err.code, raw
    except urllib.error.URLError as err:
        return 0, str(err.reason)


def wait_for_health(name, base_url, attempts=45):
    for _ in range(attempts):
        status, _ = http_json("GET", f"{base_url}/health", timeout=5.0)
        if status == 200:
            print(f"[OK]   {name} is healthy")
            return True
        time.sleep(2)
    print(f"[FAIL] {name} not healthy at {base_url}/health")
    return False


def as_email(body, name):
    return (
        "From: broker@example-brokerage.test\n"
        "To: submissions@our-mga.test\n"
        f"Subject: Quote request - {name}\n\n{body}"
    )


def run_case(case):
    path = SAMPLES_DIR / case.filename
    if not path.exists():
        return {"label": case.label, "ok": False, "actual": f"FILE_NOT_FOUND {path}"}

    cid = str(uuid.uuid4())
    payload = {
        "source_id": f"SMOKE-{path.stem}-{cid[:8]}",
        "source_type": "BROKER_EMAIL",
        "document_name": case.filename,
        "content": as_email(path.read_text(encoding="utf-8"), path.stem),
        "language": "en",
        "overrides": case.overrides,
        "persist": case.persist,
    }
    start = time.perf_counter()
    status, body = http_json(
        "POST", f"{UNDERWRITING_URL}/extract-and-underwrite", payload
    )
    elapsed = round(time.perf_counter() - start, 1)

    if status != 200 or not isinstance(body, dict):
        return {
            "label": case.label,
            "ok": False,
            "actual": f"HTTP {status}",
            "detail": body,
            "seconds": elapsed,
        }

    decision = body.get("decision") or {}
    actual = str(body.get("workflow_status"))
    persisted = bool(body.get("persisted"))
    ok = (
        actual == case.expected
        and persisted == case.persist
        and (
            case.expected_decision is None
            or decision.get("decision") == case.expected_decision
        )
    )
    return {
        "label": case.label,
        "ok": ok,
        "expected": case.expected,
        "actual": actual,
        "decision": decision.get("decision"),
        "expected_decision": case.expected_decision,
        "persisted": persisted,
        "missing_fields": body.get("missing_fields"),
        "evidence_status": decision.get("evidence_retrieval_status"),
        "evidence_count": len(decision.get("evidence") or []),
        "portfolio_status": (decision.get("portfolio_context") or {}).get("status"),
        "decision_id": decision.get("decision_id") if persisted else None,
        "seconds": elapsed,
        "raw": body,
    }


def check_audit_trail(decision_id):
    status, body = http_json(
        "GET", f"{UNDERWRITING_URL}/decisions/{decision_id}/audit-trail"
    )
    count = len(body) if isinstance(body, list) else "n/a"
    print(f"       audit-trail HTTP {status}, events: {count}")


def check_rag() -> bool:
    payload = {
        "request_id": "SMOKE-RAG-001",
        "top_k": 3,
        "queries": [
            {
                "supported_finding_id": "UW-CYB-003",
                "query": (
                    "What are the multi-factor authentication requirements "
                    "for cyber insurance underwriting?"
                ),
            }
        ],
    }
    status, body = http_json("POST", f"{KNOWLEDGE_URL}/v1/retrieve-evidence", payload)
    state = body.get("retrieval_status") if isinstance(body, dict) else None
    n_cit = len(body.get("citations") or []) if isinstance(body, dict) else 0
    ok = status == 200 and state == "SUCCESS" and n_cit > 0
    print(
        f"[{'PASS' if ok else 'DIFF'}] rag retrieve-evidence: "
        f"HTTP {status}, retrieval_status={state}, citations={n_cit}"
    )
    return ok


def main():
    print("== Health checks ==")
    services = {
        "submission-extractor": EXTRACTOR_URL,
        "knowledge-agent": KNOWLEDGE_URL,
        "underwriting-agent": UNDERWRITING_URL,
        "data-analyst-agent": ANALYST_URL,
        "email-intake": INTAKE_URL,
    }
    if not all([wait_for_health(n, u) for n, u in services.items()]):
        return 2

    print("\n== RAG index ==")
    all_ok = check_rag()

    print("\n== End-to-end cases ==")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        r = run_case(case)
        all_ok &= bool(r["ok"])
        print(f"[{'PASS' if r['ok'] else 'DIFF'}] {r['label']}")
        for key in (
            "expected",
            "actual",
            "expected_decision",
            "decision",
            "persisted",
            "missing_fields",
            "evidence_status",
            "evidence_count",
            "portfolio_status",
            "detail",
            "seconds",
        ):
            if r.get(key) not in (None, [], ""):
                print(f"       {key}: {r[key]}")
        if r.get("persisted"):
            slug = re.sub(r"[^a-z0-9]+", "_", r["label"].lower()).strip("_")
            (OUTPUT_DIR / f"{slug}.json").write_text(
                json.dumps(r["raw"], indent=2, ensure_ascii=False), encoding="utf-8"
            )
        if r.get("decision_id"):
            check_audit_trail(str(r["decision_id"]))

    print("\nRESULT:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
