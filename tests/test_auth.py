"""Tests for GitHub identity resolution via the GitHub REST API."""

import json
import ssl
import urllib.error
from email.message import Message
from unittest.mock import MagicMock, patch

from formtuitous.auth import create_ssl_context, fetch_github_identity


class TestFetchGithubIdentity:
    """Tests for fetch_github_identity."""

    def test_valid_token_returns_identity(self) -> None:
        """A valid token returns a GitHubIdentity with username and url."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"login": "octocat", "html_url": "https://github.com/octocat"}
        ).encode("utf-8")
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response
        with patch(
            "urllib.request.urlopen", return_value=mock_context
        ) as mock_urlopen:
            identity = fetch_github_identity("ghp_valid_token")
        mock_urlopen.assert_called_once()
        assert identity is not None
        assert identity.username == "octocat"
        assert identity.profile_url == "https://github.com/octocat"

    def test_http_error_returns_none(self) -> None:
        """An HTTP error (e.g., 401) returns None."""
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                url="https://api.github.com/user",
                code=401,
                msg="Unauthorized",
                hdrs=Message(),
                fp=None,
            ),
        ):
            assert fetch_github_identity("ghp_bad_token") is None

    def test_network_error_returns_none(self) -> None:
        """A network error returns None."""
        with patch(
            "urllib.request.urlopen",
            side_effect=TimeoutError("timed out"),
        ):
            assert fetch_github_identity("ghp_token") is None

    def test_malformed_json_returns_none(self) -> None:
        """A malformed JSON response returns None."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"not json"
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response
        with patch("urllib.request.urlopen", return_value=mock_context):
            assert fetch_github_identity("ghp_token") is None

    def test_missing_fields_returns_none(self) -> None:
        """A response without login or html_url returns None."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"id": 1}).encode("utf-8")
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response
        with patch("urllib.request.urlopen", return_value=mock_context):
            assert fetch_github_identity("ghp_token") is None

    def test_token_in_bearer_header(self) -> None:
        """The token is sent as a Bearer authorization header."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"login": "octocat", "html_url": "https://github.com/octocat"}
        ).encode("utf-8")
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response
        with patch(
            "urllib.request.urlopen", return_value=mock_context
        ) as mock_urlopen:
            fetch_github_identity("ghp_secret_token")
        request = mock_urlopen.call_args[0][0]
        headers = request.headers
        assert headers["Authorization"] == "Bearer ghp_secret_token"
        # urllib capitalizes header keys (User-Agent becomes User-agent)
        user_agent = headers.get("User-Agent") or headers.get("User-agent")
        assert user_agent == "formtuitous"


class TestCreateSslContext:
    """Tests for create_ssl_context."""

    def test_returns_ssl_context(self) -> None:
        """create_ssl_context always returns an SSLContext."""
        context = create_ssl_context()
        assert isinstance(context, ssl.SSLContext)

    def test_respects_env_var(self) -> None:
        """create_ssl_context uses the default context when SSL_CERT_FILE is set."""
        with patch.dict("os.environ", {"SSL_CERT_FILE": "/custom/ca.pem"}):
            context = create_ssl_context()
        assert isinstance(context, ssl.SSLContext)

    def test_finds_ca_bundle(self) -> None:
        """create_ssl_context uses a known CA bundle path when present."""
        with patch("pathlib.Path.is_file", return_value=True):
            with patch.dict("os.environ", {}, clear=True):
                context = create_ssl_context()
        assert isinstance(context, ssl.SSLContext)

    def test_no_ca_bundle_falls_back_to_default(self) -> None:
        """create_ssl_context falls back when no candidate exists.

        This exercises the Windows and macOS path, where none of the
        Linux CA bundle locations are present and the default context is
        used.
        """
        with patch("pathlib.Path.is_file", return_value=False):
            with patch.dict("os.environ", {}, clear=True):
                context = create_ssl_context()
        assert isinstance(context, ssl.SSLContext)
