"""Tests for the password resolution in the root auth.py (SCRUM-71)."""
from unittest.mock import MagicMock, patch

import auth


def test_password_from_keyring_first():
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = "secret-from-vault"
    with patch.dict("sys.modules", {"keyring": mock_keyring}), \
         patch.dict("os.environ", {"ZERODHA_PASSWORD": "env-password"}):
        assert auth._get_password("LLY803") == "secret-from-vault"
    mock_keyring.get_password.assert_called_once_with("trading-bot", "LLY803")


def test_password_falls_back_to_env_when_keyring_empty():
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = None
    with patch.dict("sys.modules", {"keyring": mock_keyring}), \
         patch.dict("os.environ", {"ZERODHA_PASSWORD": "env-password"}):
        assert auth._get_password("LLY803") == "env-password"


def test_password_falls_back_when_keyring_raises():
    mock_keyring = MagicMock()
    mock_keyring.get_password.side_effect = RuntimeError("no backend")
    with patch.dict("sys.modules", {"keyring": mock_keyring}), \
         patch.dict("os.environ", {"ZERODHA_PASSWORD": "env-password"}):
        assert auth._get_password("LLY803") == "env-password"


def test_password_none_when_nowhere():
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = None
    with patch.dict("sys.modules", {"keyring": mock_keyring}), \
         patch.dict("os.environ", {}, clear=False):
        with patch("auth.os.getenv", return_value=None):
            assert auth._get_password("LLY803") is None
