from __future__ import annotations

from ui.components.theme import html_escape, normalize_tone, tone_class


def test_normalize_tone_accepts_supported_values():
    assert normalize_tone("positive") == "positive"
    assert normalize_tone("premium") == "premium"


def test_normalize_tone_falls_back_to_neutral():
    assert normalize_tone("unknown") == "neutral"
    assert normalize_tone(None) == "neutral"


def test_tone_class_uses_normalized_tone():
    assert tone_class("avm-badge", "warning") == "avm-badge--warning"
    assert tone_class("avm-badge", "loud") == "avm-badge--neutral"


def test_html_escape_handles_markup_and_none():
    assert html_escape("<b>Ñuñoa</b>") == "&lt;b&gt;Ñuñoa&lt;/b&gt;"
    assert html_escape(None) == ""
