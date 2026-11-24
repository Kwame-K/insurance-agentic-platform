"""Smoke test: broker email -> extractor -> underwriting -> (RAG) -> decision."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any
import re

UNDERWRITING_URL = "http://localhost:8002"
EXTRACTOR_URL = "http://localhost:8000"
KNOWLEDGE_URL = "http://localhost:8001"

SAMPLES_DIR = (
    Path(__file__).resolve().parents[2]
    / "insurance-submission-extractor"
    / "data"
    / "synthetic"
)

# (fichier, résultat attendu) - hypothèses à confirmer lors du premier lancement
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Case:
    label: str
    filename: str
    expected: str
    overrides: dict[str, Any] = field(default_factory=dict)
    persist: bool = False
    expected_decision: str | None = None


CYBER_OVERRIDES: dict[str, Any] = {
    "mfa_enabled": True,
    "requested_limit_cad": 1_000_000,
    "requested_retention_cad": 10_000,
}

CASES: list[Case] = [
    Case("cyber - champs manquants", "cyber_submission.txt", "PENDING_INFORMATION"),
    Case(
        "cyber - complété par overrides",
        "cyber_submission.txt",
        "EVALUATED",
        overrides=CYBER_OVERRIDES,
        persist=True,
        expected_decision="ACCEPT"
    ),
    Case("incomplet", "incomplete_submission.txt", "PENDING_INFORMATION"),
    Case("hors périmètre", "restaurant_submission.txt", "UNSUPPORTED_SUBMISSION"),
    Case(
        "cyber - limite hors autorité (RAG)",
        "cyber_submission.txt",
        "EVALUATED",
        overrides={**CYBER_OVERRIDES, "requested_limit_cad": 3_000_000},
        persist=True,
        expected_decision="REFER",
    ),

]


def run_case(case: Case) -> dict[str, Any]:
    path = SAMPLES_DIR / case.filename
    if not path.exists():
        return {"label": case.label,
        "ok": (
            actual == case.expected
            and persisted == case.persist
            and (case.expected_decision is None or decision.get("decision") == case.expected_decision)
        ),
        "actual": "FILE_NOT_FOUND"}

    correlation_id = str(uuid.uuid4())
    payload = {
        "source_id": f"SMOKE-{path.stem}-{correlation_id[:8]}",
        "source_type": "BROKER_EMAIL",
        "document_name": case.filename,
        "content": as_email(path.read_text(encoding="utf-8"), path.stem),
        "language": "en",
        "overrides": case.overrides,
        "persist": case.persist,
    }

    started = time.perf_counter()
    status, body = http_json("POST", f"{UNDERWRITING_URL}/extract-and-underwrite", payload)
    elapsed = round(time.perf_counter() - started, 1)

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
    return {
        "label": case.label,
        "ok": actual == case.expected and persisted == case.persist,
        "expected": case.expected,
        "actual": actual,
        "decision": decision.get("decision"),
        "persisted": persisted,
        "missing_fields": body.get("missing_fields"),
        "overridden_fields": body.get("overridden_fields"),
        "message": body.get("message"),
        "decision_id": decision.get("decision_id") if persisted else None,
        "seconds": elapsed,
        "raw": body,
        "evidence_status": decision.get("evidence_retrieval_status"),
        "evidence_count": len(decision.get("evidence") or []),
        "portfolio_status": (decision.get("portfolio_context") or {}).get("status"),

    }

def http_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 120.0,
) -> tuple[int, dict[str, Any] | list[Any] | str]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        body = error.read().decode()
        try:
            return error.code, json.loads(body)
        except json.JSONDecodeError:
            return error.code, body
    except urllib.error.URLError as error:
        return 0, str(error.reason)


def wait_for_health(name: str, base_url: str, attempts: int = 30) -> bool:
    for _ in range(attempts):
        status, _ = http_json("GET", f"{base_url}/health", timeout=5.0)
        if status == 200:
            print(f"[OK]   {name} is healthy")
            return True
        time.sleep(2)
    print(f"[FAIL] {name} did not become healthy at {base_url}/health")
    return False


def as_email(body: str, name: str) -> str:
    return (
        "From: broker@example-brokerage.test\n"
        "To: submissions@our-mga.test\n"
        f"Subject: Quote request - {name}\n\n"
        f"{body}"
    )


def check_audit_trail(decision_id: str) -> None:
    status, body = http_json("GET", f"{UNDERWRITING_URL}/decisions/{decision_id}/audit-trail")
    count = len(body) if isinstance(body, list) else "n/a"
    print(f"       audit-trail HTTP {status}, events: {count}")


def main() -> int:
    print("== Health checks ==")
    healthy = all(
        [
            wait_for_health("submission-extractor", EXTRACTOR_URL),
            wait_for_health("knowledge-agent", KNOWLEDGE_URL),
            wait_for_health("underwriting-agent", UNDERWRITING_URL),
        ]
    )
    if not healthy:
        return 2

        print("\n== End-to-end cases ==")
    results = [run_case(case) for case in CASES]

    for result in results:
        flag = "PASS" if result["ok"] else "DIFF"
        print(f"[{flag}] {result['label']}")
        
        if result.get("persisted"):
            out = Path(__file__).resolve().parent / "smoke_output"
            out.mkdir(exist_ok=True)
            slug = re.sub(r"[^a-z0-9]+", "_", result["label"].lower()).strip("_")
            (out / f"{slug}.json").write_text(
                json.dumps(result["raw"], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        for key in (
            "expected", "actual", "decision", "persisted", "missing_fields",
            "overridden_fields", "evidence_status", "evidence_count",
            "portfolio_status", "message", "detail", "seconds",
        ):

            if result.get(key) not in (None, [], ""):
                print(f"       {key}: {result[key]}")
        if result.get("decision_id"):
            check_audit_trail(str(result["decision_id"]))

if __name__ == "__main__":
    sys.exit(main())
