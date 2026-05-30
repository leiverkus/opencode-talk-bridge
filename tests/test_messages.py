from __future__ import annotations

from opencode_talk_bridge.messages import translator


def test_default_german():
    t = translator("de")
    assert t("aborted") == "🛑 Abgebrochen."


def test_english_override():
    t = translator("en")
    assert t("aborted") == "🛑 Aborted."
    assert "working" in t("working").lower()


def test_unknown_locale_falls_back_to_german():
    t = translator("fr")
    assert t("aborted") == "🛑 Abgebrochen."


def test_unknown_key_returns_key():
    t = translator("de")
    assert t("nope_not_a_key") == "nope_not_a_key"


def test_formatting_fields():
    t = translator("en")
    assert t("model_set", model="anthropic/claude") == "✅ Model set: anthropic/claude"


def test_help_localised():
    assert "Befehle" in translator("de")("help")
    assert "Commands" in translator("en")("help")
