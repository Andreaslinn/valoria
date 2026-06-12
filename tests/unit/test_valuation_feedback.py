from __future__ import annotations

import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.valuations import router as valuations_router
from scripts.summarize_valuation_feedback import summarize_feedback, write_feedback_summary
from services.valuation_feedback import build_valuation_feedback_record, record_valuation_feedback
from ui.valuation.result import submit_valuation_feedback_via_api


def test_build_valuation_feedback_record_captures_beta_fields() -> None:
    record = build_valuation_feedback_record(
        valuation_result={
            "estimated_price_clp": 120_000_000,
            "estimated_price_uf": 3_200,
            "confidence": 0.67,
            "comparable_quality_level": "acceptable",
            "beta_scope_status": "beta_supported",
            "comparable_count": 9,
        },
        valuation_payload={
            "comuna": "san_miguel",
            "property_type": "apartment",
            "built_area_m2": 58,
        },
        feedback="reasonable",
        comment="Se ve dentro de mercado.",
        occurred_at=datetime(2026, 5, 27, 12, 0, tzinfo=UTC),
    )

    assert record == {
        "timestamp": "2026-05-27T12:00:00+00:00",
        "comuna": "san_miguel",
        "property_type": "apartment",
        "m2": 58,
        "estimated_value_clp": 120_000_000,
        "estimated_value_uf": 3_200,
        "confidence": "medium",
        "confidence_score": 0.67,
        "confidence_label": "medium",
        "comparable_quality_level": "acceptable",
        "beta_scope_status": "beta_supported",
        "comparable_count": 9,
        "feedback": "reasonable",
        "comment": "Se ve dentro de mercado.",
    }


def test_build_valuation_feedback_record_rejects_unknown_feedback() -> None:
    with pytest.raises(ValueError, match="Unsupported valuation feedback"):
        build_valuation_feedback_record(
            valuation_result={},
            valuation_payload={},
            feedback="buy_now",
        )


def test_record_valuation_feedback_appends_jsonl() -> None:
    output_dir = _test_output_dir("jsonl")
    try:
        path = record_valuation_feedback(
            {
                "timestamp": "2026-05-27T12:00:00+00:00",
                "feedback": "too_high",
                "comuna": "macul",
            },
            output_dir=output_dir,
        )

        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert path.parent == output_dir
        assert path.name.startswith("valuation_feedback_")
        assert rows == [{"timestamp": "2026-05-27T12:00:00+00:00", "feedback": "too_high", "comuna": "macul"}]
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def test_valuation_feedback_endpoint_persists_jsonl(monkeypatch) -> None:
    output_dir = _test_output_dir("endpoint")
    try:
        monkeypatch.setenv("VALUATION_FEEDBACK_DIR", str(output_dir))
        app = FastAPI()
        app.include_router(valuations_router, prefix="/api/v1")
        client = TestClient(app)

        response = client.post(
            "/api/v1/valuations/feedback",
            json={
                "valuation_result": {
                    "estimated_price_clp": 180_000_000,
                    "estimated_price_uf": 4864.86,
                    "confidence_score": 0.82,
                    "confidence_label": "high",
                    "comparable_quality_level": "strong",
                    "beta_scope_status": "beta_supported",
                    "comparable_count": 12,
                },
                "valuation_payload": {
                    "comuna": "nunoa",
                    "property_type": "apartment",
                    "m2": 75,
                },
                "feedback": "reasonable",
                "comment": "calza con mercado",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["record"]["feedback"] == "reasonable"
        files = list(output_dir.glob("valuation_feedback_*.jsonl"))
        assert len(files) == 1
        rows = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
        assert rows[0]["comuna"] == "nunoa"
        assert rows[0]["comment"] == "calza con mercado"
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def test_valuation_feedback_endpoint_rejects_unknown_feedback(monkeypatch) -> None:
    output_dir = _test_output_dir("endpoint-invalid")
    try:
        monkeypatch.setenv("VALUATION_FEEDBACK_DIR", str(output_dir))
        app = FastAPI()
        app.include_router(valuations_router, prefix="/api/v1")
        client = TestClient(app)

        response = client.post(
            "/api/v1/valuations/feedback",
            json={
                "valuation_result": {},
                "valuation_payload": {},
                "feedback": "buy_now",
            },
        )

        assert response.status_code == 400
        assert "Unsupported valuation feedback" in response.json()["detail"]
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def test_ui_submit_valuation_feedback_uses_api_client() -> None:
    class FakeApiClient:
        def __init__(self) -> None:
            self.calls = []

        def submit_valuation_feedback(self, **kwargs):
            self.calls.append(kwargs)
            return {"status": "ok", "record": {"feedback": kwargs["feedback"]}, "path": "x.jsonl"}

    client = FakeApiClient()

    response = submit_valuation_feedback_via_api(
        client,
        valuation_result={"estimated_price_clp": 180_000_000},
        valuation_payload={"comuna": "nunoa"},
        feedback="too_low",
        comment="sector caro",
    )

    assert response["status"] == "ok"
    assert client.calls == [
        {
            "valuation_result": {"estimated_price_clp": 180_000_000},
            "valuation_payload": {"comuna": "nunoa"},
            "feedback": "too_low",
            "comment": "sector caro",
        }
    ]


def test_summarize_feedback_groups_private_beta_responses() -> None:
    output_dir = _test_output_dir("summary")
    summary = summarize_feedback(
        [
            {
                "timestamp": "2026-05-27T12:00:00+00:00",
                "feedback": "reasonable",
                "property_type": "apartment",
                "comuna": "san_miguel",
                "comparable_quality_level": "acceptable",
                "confidence": "medium",
                "estimated_value_clp": 120_000_000,
                "comment": "Ok para el sector.",
            },
            {
                "timestamp": "2026-05-27T13:00:00+00:00",
                "feedback": "too_low",
                "property_type": "house",
                "comuna": "la_florida",
                "comparable_quality_level": "weak",
                "confidence": "low",
                "estimated_value_clp": 180_000_000,
                "comment": "",
            },
        ]
    )

    assert summary["summary"]["total_feedback"] == 2
    assert summary["summary"]["latest_feedback_at"] == "2026-05-27T13:00:00+00:00"
    assert summary["by_feedback"] == {"reasonable": 1, "too_low": 1}
    assert summary["by_property_type"] == {"apartment": 1, "house": 1}
    assert summary["by_comuna"] == {"san_miguel": 1, "la_florida": 1}
    assert summary["avg_estimated_value_clp_by_feedback"] == {
        "reasonable": 120_000_000,
        "too_low": 180_000_000,
    }
    assert summary["comments"][0]["comment"] == "Ok para el sector."

    try:
        md_path, json_path = write_feedback_summary(summary, output_dir=output_dir)
        assert md_path.exists()
        assert json_path.exists()
        assert "AVM Valuation Feedback Summary" in md_path.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def _test_output_dir(name: str) -> Path:
    path = Path("reports/test_valuation_feedback") / f"{name}-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path
