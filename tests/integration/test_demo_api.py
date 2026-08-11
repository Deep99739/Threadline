from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from threadline.api import create_app
from threadline.demo import DEMO_TENANT_ID, run_demo


def _seeded_client(tmp_path: Path) -> tuple[TestClient, str]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'api.db'}"
    run_demo(database_url, tmp_path / "demo-repository")
    return TestClient(create_app(database_url)), database_url


def test_health_and_demo_surface_real_partial_handoff(tmp_path: Path) -> None:
    client, _ = _seeded_client(tmp_path)

    with client:
        assert client.get("/api/health").json() == {
            "status": "ok",
            "mode": "synthetic-read-only",
        }
        response = client.get("/api/demo")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "partial"
    assert payload["repository"]["branch"] == "feature/retry-jobs"
    assert len(payload["repository"]["commit"]) == 40
    assert payload["next_action"]
    assert payload["unknowns"]
    assert payload["conflicts"]
    assert payload["items"]


def test_cited_evidence_can_be_opened_but_unscoped_evidence_cannot(
    tmp_path: Path,
) -> None:
    client, _ = _seeded_client(tmp_path)

    with client:
        payload = client.get("/api/demo").json()
        evidence_id = next(
            citation["evidence_id"] for item in payload["items"] for citation in item["citations"]
        )
        cited = client.get(f"/api/evidence/{evidence_id}")
        missing = client.get(f"/api/evidence/{uuid4()}")

    assert cited.status_code == 200
    assert cited.json()["evidence_id"] == evidence_id
    assert cited.json()["content"]
    assert missing.status_code == 404


def test_decision_discloses_asserted_approval_and_missing_key(tmp_path: Path) -> None:
    client, _ = _seeded_client(tmp_path)

    with client:
        payload = client.get("/api/demo").json()
        decision_ref = next(
            item["entity_id"] for item in payload["items"] if item["entity_type"] == "decision"
        )
        decision = client.get(f"/api/decisions/{decision_ref}")
        missing = client.get("/api/decisions/not-a-real-decision")

    assert decision.status_code == 200
    assert decision.json()["epistemic_state"] == "ASSERTED"
    assert "does not authenticate" in decision.json()["warning"]
    assert missing.status_code == 404


def test_demo_requires_explicit_seed(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'empty.db'}"
    run_demo(database_url, tmp_path / "seed-repository")

    from threadline.storage import ThreadlineStore

    store = ThreadlineStore(database_url)
    try:
        store.reset_tenant_for_demo(DEMO_TENANT_ID)
    finally:
        store.close()

    with TestClient(create_app(database_url)) as client:
        response = client.get("/api/demo")

    assert response.status_code == 503
