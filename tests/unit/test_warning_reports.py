import pytest
from core.assessment.warnings import warning_detail
from services.reports import _include_model_warnings


@pytest.mark.parametrize("code", ["property_type_not_allowed", "delta_vs_baseline_too_high", "published_price_not_provided", "future_warning"])
def test_report_keeps_warning_code_and_shared_translation(code):
    html = _include_model_warnings('<main></main>', {"warnings": [code]})
    assert code in html
    assert warning_detail(code)["description"] in html


def test_unknown_warning_is_escaped():
    html = _include_model_warnings('<main></main>', {"warnings": ['<script>alert(1)</script>']})
    assert '<script>' not in html
