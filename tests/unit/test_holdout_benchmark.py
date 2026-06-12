from decimal import Decimal

import pytest

from scripts.holdout_benchmark import (
    evaluate_holdout,
    generate_stratified_holdout,
    summarize_rows,
    training_pool_for_holdout,
)
from tests.unit.factories import make_listing

UF = Decimal("37000")


def _listing(index: int, **kwargs):
    listing = make_listing(fingerprint=f"fp-{index}", **kwargs)
    listing.id = index
    return listing


def test_generate_stratified_holdout_by_comuna_and_property_type() -> None:
    listings = [
        _listing(i, comuna="nunoa", property_type="apartment")
        for i in range(1, 21)
    ] + [
        _listing(i, comuna="nunoa", property_type="house", m2=140, built_area_m2=140, land_area_m2=300)
        for i in range(101, 121)
    ]

    holdout = generate_stratified_holdout(listings, fraction=0.2, min_segment_size=10, seed=7)

    assert len(holdout["listing_ids"]) == 8
    strata = {(row["comuna"], row["property_type"]): row for row in holdout["strata"]}
    assert strata[("nunoa", "apartment")]["holdout_count"] == 4
    assert strata[("nunoa", "house")]["holdout_count"] == 4


def test_training_pool_excludes_all_holdout_ids() -> None:
    listings = [_listing(i) for i in range(1, 11)]
    training = training_pool_for_holdout(listings, {1, 2, 3})

    assert {listing.id for listing in training} == set(range(4, 11))


def test_evaluate_holdout_rejects_leakage_into_training_pool() -> None:
    holdout = [_listing(1)]
    training = [_listing(1), _listing(2), _listing(3), _listing(4), _listing(5), _listing(6)]

    with pytest.raises(ValueError, match="holdout leakage"):
        evaluate_holdout(holdout, training, uf_to_clp=UF)


def test_holdout_evaluation_uses_training_pool_only() -> None:
    holdout = [_listing(100, price_clp=180_000_000)]
    training = [
        _listing(i, price_clp=180_000_000)
        for i in range(1, 7)
    ]

    rows = evaluate_holdout(holdout, training, uf_to_clp=UF)

    assert rows[0].status == "ok"
    assert rows[0].comparables_used == 6


def test_segments_with_low_n_are_marked_insufficient() -> None:
    rows = evaluate_holdout(
        [_listing(100, price_clp=180_000_000)],
        [_listing(i, price_clp=180_000_000) for i in range(1, 7)],
        uf_to_clp=UF,
    )

    summary = summarize_rows(rows, all_targets=[_listing(100)], min_samples=5, uf_to_clp=UF)

    assert summary["status"] == "insufficient_data"
    assert summary["by_property_type"]["apartment"]["status"] == "insufficient"
