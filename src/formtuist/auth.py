"""GitHub identity resolution for form authentication."""

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# endpoint that returns the authenticated GitHub user for a token
GITHUB_API_USER_URL = "https://api.github.com/user"
GITHUB_USER_AGENT = "formtuist"
GITHUB_API_TIMEOUT_SECONDS = 10

# common locations for the system CA certificate bundle; Python builds on
# some platforms (e.g., NixOS) do not locate these by default
CA_BUNDLE_CANDIDATES = [
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/ssl/certs/ca-bundle.crt",
    "/nix/var/nix/profiles/default/etc/ssl/certs/ca-bundle.crt",
    "/nix/var/nix/profiles/default/etc/ssl/certs/ca-certificates.crt",
]

LOGIN_KEY = "login"
PROFILE_URL_KEY = "html_url"


class GitHubIdentity(BaseModel):
    """The public identity associated with a GitHub token."""

    username: str
    profile_url: str


def create_ssl_context() -> ssl.SSLContext:
    """Return an SSL context that can verify GitHub's certificate.

    Python builds on some platforms fail to locate the system CA bundle,
    causing CERTIFICATE_VERIFY_FAILED during the TLS handshake.  When the
    SSL_CERT_FILE or SSL_CERT_DIR environment variables are set the
    default context is used (it honours them).  Otherwise the well-known
    CA bundle locations are tried explicitly before falling back to the
    default context.
    """
    if "SSL_CERT_FILE" in os.environ or "SSL_CERT_DIR" in os.environ:
        return ssl.create_default_context()
    for cafile in CA_BUNDLE_CANDIDATES:
        if Path(cafile).is_file():
            try:
                return ssl.create_default_context(cafile=cafile)
            except (ssl.SSLError, OSError):
                continue
    return ssl.create_default_context()


def fetch_github_identity(token: str) -> GitHubIdentity | None:
    """Return the GitHub identity for a token, or None when invalid.

    Calls the GitHub REST API and extracts the username and profile URL.
    Any HTTP error, network failure, timeout, or malformed response
    results in a None return value so that callers can block submission.
    """
    request = urllib.request.Request(
        GITHUB_API_USER_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": GITHUB_USER_AGENT,
        },
    )
    context = create_ssl_context()
    try:
        with urllib.request.urlopen(
            request, timeout=GITHUB_API_TIMEOUT_SECONDS, context=context
        ) as response:
            data: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ):
        return None
    username = data.get(LOGIN_KEY)
    profile_url = data.get(PROFILE_URL_KEY)
    if not isinstance(username, str) or not isinstance(profile_url, str):
        return None
    return GitHubIdentity(username=username, profile_url=profile_url)
