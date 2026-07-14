import pytest
from unittest.mock import MagicMock, mock_open, patch

from src.auth import AuthenticationError, load_kite_session


def _mock_kite(profile_ok=True):
    kite = MagicMock()
    if profile_ok:
        kite.profile.return_value = {"user_name": "Vishal Krishna", "user_id": "ZV1234"}
    else:
        kite.profile.side_effect = Exception("Invalid token")
    return kite


@patch("src.auth.os.getenv")
@patch("src.auth.os.path.exists", return_value=True)
@patch("builtins.open", mock_open(read_data="valid_access_token_abc123"))
@patch("src.auth.KiteConnect")
def test_load_kite_session_success(mock_kc, mock_exists, mock_getenv):
    mock_getenv.side_effect = lambda k, default=None: {
        "KITE_API_KEY": "sd2jkdcoab56o336",
        "KITE_ACCESS_TOKEN_PATH": "./token.txt",
    }.get(k, default)
    mock_kc.return_value = _mock_kite(profile_ok=True)

    kite = load_kite_session()
    assert kite is not None
    mock_kc.return_value.set_access_token.assert_called_once_with("valid_access_token_abc123")


@patch("src.auth.os.getenv", return_value=None)
def test_missing_api_key_raises(mock_getenv):
    with pytest.raises(AuthenticationError, match="KITE_API_KEY"):
        load_kite_session()


@patch("src.auth.os.getenv")
@patch("src.auth.os.path.exists", return_value=False)
def test_missing_token_file_raises(mock_exists, mock_getenv):
    mock_getenv.side_effect = lambda k, default=None: {
        "KITE_API_KEY": "sd2jkdcoab56o336",
        "KITE_ACCESS_TOKEN_PATH": "./token.txt",
    }.get(k, default)
    with pytest.raises(AuthenticationError, match="Token file not found"):
        load_kite_session()


@patch("src.auth.os.getenv")
@patch("src.auth.os.path.exists", return_value=True)
@patch("builtins.open", mock_open(read_data="   "))
def test_empty_token_file_raises(mock_exists, mock_getenv):
    mock_getenv.side_effect = lambda k, default=None: {
        "KITE_API_KEY": "sd2jkdcoab56o336",
        "KITE_ACCESS_TOKEN_PATH": "./token.txt",
    }.get(k, default)
    with pytest.raises(AuthenticationError, match="empty"):
        load_kite_session()


@patch("src.auth.os.getenv")
@patch("src.auth.os.path.exists", return_value=True)
@patch("builtins.open", mock_open(read_data="expired_token"))
@patch("src.auth.KiteConnect")
def test_invalid_token_raises(mock_kc, mock_exists, mock_getenv):
    mock_getenv.side_effect = lambda k, default=None: {
        "KITE_API_KEY": "sd2jkdcoab56o336",
        "KITE_ACCESS_TOKEN_PATH": "./token.txt",
    }.get(k, default)
    mock_kc.return_value = _mock_kite(profile_ok=False)
    with pytest.raises(AuthenticationError, match="Token validation failed"):
        load_kite_session()
