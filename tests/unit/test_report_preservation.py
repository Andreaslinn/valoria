from services.reports import build_property_valuation_report_html, _include_analysis_evidence


def test_report_preserves_user_comparison_independently_from_estimate():
    result = {"estimated_price_uf":2375.9, "warnings":["delta_vs_baseline_too_high"],
              "comparables":[{"listing_id":20,"title":"Comparable real","source":"yapo",
                              "external_id":"pub-20","url":"https://www.yapo.cl/test/20"}]}
    html = build_property_valuation_report_html(valuation_result=result,
        valuation_payload={"target_listing_id":1130,"comuna":"independencia","m2":50,"precio_publicado_uf":1520})
    assert '<strong>1520</strong>' in html
    assert 'Precio publicado no requerido' not in html
    assert 'No aplica sin precio publicado.' not in html
    assert 'delta_vs_baseline_too_high' in html
    assert 'Comparable real' in html and 'pub-20' in html and 'yapo' in html
    assert 'href="https://www.yapo.cl/test/20"' in html


def test_comparable_links_never_invented_or_scriptable():
    html = _include_analysis_evidence('<main></main>', {"comparables":[
        {"title":"Missing","url":None},{"title":"Unsafe","url":"javascript:alert(1)"}]}, {})
    assert 'href=' not in html


def test_historical_report_retains_observation_and_source():
    from services.reports import build_listing_analysis_report_html
    html = build_listing_analysis_report_html(analysis={
        "listing": {"listing_id":298,"status":"removed","source":"yapo",
                    "last_seen_at":"2026-06-05T16:23:39Z","title":"Histórica","price_uf":3100},
        "valuation": {"estimated_value_uf":2971.57}, "price_analysis":{}})
    assert 'Retirada / Histórica' in html
    assert '2026-06-05T16:23:39Z' in html
    assert 'yapo' in html
