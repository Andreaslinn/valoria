import json
import logging

import pytest

from core.exceptions import ValidationError
from workers.rejection_logging import rejection_record


@pytest.mark.parametrize("field,value,message,reason", [
    ("price_clp", 3008, "price_clp 3008 bajo el minimo (10000000)", "below_minimum"),
    ("bedrooms", 11, "bedrooms fuera de rango [0, 10]: 11", "out_of_range"),
    ("bathrooms", 20, "bathrooms fuera de rango [0, 10]: 20", "out_of_range"),
    ("m2", None, "Campo requerido ausente: 'm2'", "required_missing"),
])
def test_rejection_identifies_listing_field_value_and_reason(field, value, message, reason):
    record = rejection_record({"source": "yapo", "external_id": "123", field: value}, ValidationError(message))
    assert (record["listing_id"], record["source"], record["field"], record["received_value"], record["reason"]) == ("123", "yapo", field, value, reason)


def test_untrusted_html_urls_secrets_and_nonfinite_values_are_not_serialized():
    secret = "<html>password=private-token</html>"
    record = rejection_record({"source": secret, "external_id": secret, "price_clp": secret,
                               "price_uf": float("nan"), "raw_metadata": {"html": secret, "uf_rate_used": secret}},
                              ValidationError("price_clp no numerico: " + secret))
    text = json.dumps(record, allow_nan=False)
    assert "private-token" not in text and "<html>" not in text
    assert record["field"] == "price_clp"


@pytest.mark.asyncio
async def test_worker_logs_rejection_without_accepting_invalid_listing(engine, caplog):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from tests.unit.test_yapo_price_pending import rows
    from workers.scraper_job import run_scraper_job

    raw = rows()[3]
    raw["price_clp"] = 3008
    raw["raw_metadata"]["html"] = "SECRET_HTML_SENTINEL"
    class Scraper:
        source_name = "yapo"
        async def scrape(self):
            return [raw]
    with caplog.at_level(logging.WARNING):
        stats = await run_scraper_job(Scraper(), async_sessionmaker(engine, expire_on_commit=False))
    assert stats.validation_errors == stats.discarded == 1
    assert stats.inserted == 0
    entry, = [r.message for r in caplog.records if r.message.startswith("listing_validation_rejected ")]
    record = json.loads(entry.split(" ", 1)[1])
    assert record["listing_id"] == raw["external_id"]
    assert record["received_value"] == 3008
    assert "SECRET_HTML_SENTINEL" not in caplog.text
