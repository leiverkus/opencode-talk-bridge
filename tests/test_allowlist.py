from __future__ import annotations

import pytest

from opencode_talk_bridge.allowlist import Allowlist


def test_empty_allowlist_rejected():
    with pytest.raises(ValueError):
        Allowlist([])
    with pytest.raises(ValueError):
        Allowlist(["", "  "])


def test_allowed_user():
    al = Allowlist(["jdoe", "asmith"])
    assert al.is_allowed("jdoe") is True
    assert al.is_allowed("asmith", "users") is True


def test_foreign_user_ignored():
    al = Allowlist(["jdoe"])
    assert al.is_allowed("mallory") is False


def test_non_user_actor_types_rejected_even_if_id_matches():
    al = Allowlist(["jdoe"])
    # A guest or bot whose id collides with an allowlisted user must not pass.
    assert al.is_allowed("jdoe", "guests") is False
    assert al.is_allowed("jdoe", "bots") is False
    assert al.is_allowed("jdoe", "federated_users") is False


def test_whitespace_in_config_is_trimmed():
    al = Allowlist([" jdoe ", "asmith\n"])
    assert al.is_allowed("jdoe")
    assert "asmith" in al
