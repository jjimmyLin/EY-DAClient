from __future__ import annotations

import pytest

from config.settings import settings


def test_gemini_api_key_rejects_non_ascii_text():
    with pytest.raises(ValueError, match="original ASCII key"):
        settings.validate_gemini_api_key("请修复：")


def test_gemini_api_key_rejects_whitespace():
    with pytest.raises(ValueError, match="without spaces"):
        settings.validate_gemini_api_key("key with spaces")


def test_gemini_api_key_accepts_ascii_token():
    settings.validate_gemini_api_key("AIza-test_key-123")
