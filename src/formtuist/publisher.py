"""Publish a local textual-serve form through a bitbang WebRTC tunnel."""

import gzip
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from bitbang import BitBangWSGI

# response and proxy tuning constants
CHUNK_SIZE = 32768
GZIP_MIN_SIZE = 1024
POLL_INTERVAL_SECONDS = 0.5
STARTUP_TIMEOUT_SECONDS = 30
REQUEST_TIMEOUT_SECONDS = 30
HTML_CONTENT_TYPE = "text/html"
HTTP_SCHEME = "http://"
GZIP_ENCODING = "gzip"
IDENTITY_ENCODING = "identity"
BAD_GATEWAY_STATUS = "502 Bad Gateway"
TEXT_PLAIN_CONTENT_TYPE = "text/plain"

# content types that are worth compressing before sending through WebRTC
COMPRESSIBLE_PREFIXES = ("text/",)
COMPRESSIBLE_TYPES = {
    "application/javascript",
    "application/json",
    "application/manifest+json",
    "application/xhtml+xml",
    "application/xml",
    "font/otf",
    "font/ttf",
    "image/svg+xml",
}

# common CA bundle locations, including the location used by NixOS
CA_BUNDLE_CANDIDATES = (
    Path("/etc/ssl/certs/ca-certificates.crt"),
    Path("/etc/ssl/certs/ca-bundle.crt"),
)
SSL_CERT_FILE = "SSL_CERT_FILE"
SSL_CERT_DIR = "SSL_CERT_DIR"

# arguments used to launch the local formtuist server in a child process
PYTHON_MODULE_FLAG = "-m"
CLI_MODULE = "formtuist.cli"
SERVE_COMMAND = "serve"
HOST_OPTION = "--host"
PORT_OPTION = "--port"
DB_DIR_OPTION = "--db-dir"
DATABASE_NAME_OPTION = "--database-name"
CODE_DIR_OPTION = "--code-dir"

# adapter configuration
BITBANG_PROGRAM_NAME = "formtuist"


class RewritingProxy:
    """Proxy a local textual-serve instance as a WSGI application."""

    def __init__(self, target: str) -> None:
        """Store the local target and its absolute URL origin."""
        if not target.startswith(HTTP_SCHEME):
            target = f"{HTTP_SCHEME}{target}"
        self.target = target.rstrip("/")
        self._origin = self.target

    def __call__(
        self, environ: dict[str, Any], start_response: Any
    ) -> Iterable[bytes]:
        """Proxy one request and rewrite textual-serve HTML URLs."""
        method = environ["REQUEST_METHOD"]
        path = environ.get("PATH_INFO", "/")
        query = environ.get("QUERY_STRING", "")
        url = f"{self.target}{path}"
        if query:
            url += f"?{query}"
        headers = {
            key[5:].replace("_", "-").title(): value
            for key, value in environ.items()
            if key.startswith("HTTP_")
        }
        if environ.get("CONTENT_TYPE"):
            headers["Content-Type"] = environ["CONTENT_TYPE"]
        headers["Accept-Encoding"] = IDENTITY_ENCODING
        body = None
        content_length = environ.get("CONTENT_LENGTH")
        if content_length and int(content_length) > 0:
            body = environ["wsgi.input"].read(int(content_length))
        request = urllib.request.Request(
            url, data=body, headers=headers, method=method
        )
        try:
            response = urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except urllib.error.HTTPError as error:
            response = error
        except Exception as error:
            start_response(
                BAD_GATEWAY_STATUS, [("Content-Type", TEXT_PLAIN_CONTENT_TYPE)]
            )
            return [f"proxy error: {error}".encode()]
        status = f"{response.status} {response.reason}"
        content_type = response.headers.get("Content-Type", "")
        accept_encoding = environ.get("HTTP_ACCEPT_ENCODING", "").lower()
        wants_gzip = GZIP_ENCODING in accept_encoding
        if response.status in (204, 304, 101):
            start_response(status, list(response.headers.items()))
            return _iter_chunks(response)
        is_html = HTML_CONTENT_TYPE in content_type
        should_buffer = is_html or (
            wants_gzip and _is_compressible(content_type)
        )
        if should_buffer:
            data = response.read()
            response.close()
            if is_html:
                data = data.replace(self._origin.encode(), b"")
            return self._respond(
                start_response,
                status,
                response.headers,
                data,
                compress=wants_gzip,
            )
        start_response(status, list(response.headers.items()))
        return _iter_chunks(response)

    @staticmethod
    def _respond(
        start_response: Any,
        status: str,
        upstream_headers: Any,
        data: bytes,
        compress: bool = False,
    ) -> list[bytes]:
        """Return a buffered response with an exact content length."""
        encoding = None
        if compress and len(data) >= GZIP_MIN_SIZE:
            compressed = gzip.compress(data, compresslevel=6)
            if len(compressed) < len(data):
                data = compressed
                encoding = GZIP_ENCODING
        output_headers = []
        skipped_headers = {
            "content-length",
            "transfer-encoding",
            "content-encoding",
            "etag",
            "content-md5",
            "connection",
            "keep-alive",
            "proxy-connection",
        }
        for key, value in upstream_headers.items():
            if key.lower() not in skipped_headers:
                output_headers.append((key, value))
        if encoding:
            output_headers.append(("Content-Encoding", encoding))
            output_headers.append(("Vary", "Accept-Encoding"))
        output_headers.append(("Content-Length", str(len(data))))
        start_response(status, output_headers)
        return [data]


def _is_compressible(content_type: str) -> bool:
    """Return whether a response content type benefits from gzip."""
    media_type = content_type.split(";", maxsplit=1)[0].strip().lower()
    return media_type.startswith(COMPRESSIBLE_PREFIXES) or media_type in (
        COMPRESSIBLE_TYPES
    )


def _iter_chunks(response: Any) -> Iterable[bytes]:
    """Yield an upstream response body in bounded chunks."""
    try:
        while True:
            chunk = response.read(CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
    except Exception:
        return
    finally:
        response.close()


def ensure_ca_store() -> None:
    """Configure a system CA bundle when Python has no CA setting."""
    if os.environ.get(SSL_CERT_FILE) or os.environ.get(SSL_CERT_DIR):
        return
    for candidate in CA_BUNDLE_CANDIDATES:
        if candidate.is_file():
            os.environ[SSL_CERT_FILE] = str(candidate)
            return


def wait_for_server(host: str, port: int) -> None:
    """Wait for the local server to answer or raise a startup error."""
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"{HTTP_SCHEME}{host}:{port}/",
                timeout=1,
            ):
                return
        except Exception:
            time.sleep(POLL_INTERVAL_SECONDS)
    raise RuntimeError(
        f"local server on {host}:{port} did not start within "
        f"{STARTUP_TIMEOUT_SECONDS}s"
    )


def build_serve_command(  # noqa: PLR0913, PLR0917
    form_path: Path,
    host: str,
    port: int,
    db_dir: Path | None = None,
    database_name: str | None = None,
    code_dir: Path | None = None,
) -> list[str]:
    """Build the child-process command that runs textual-serve."""
    command = [
        sys.executable,
        PYTHON_MODULE_FLAG,
        CLI_MODULE,
        SERVE_COMMAND,
        str(form_path),
        HOST_OPTION,
        host,
        PORT_OPTION,
        str(port),
    ]
    if db_dir is not None:
        command.extend([DB_DIR_OPTION, str(db_dir)])
    if database_name is not None:
        command.extend([DATABASE_NAME_OPTION, database_name])
    if code_dir is not None:
        command.extend([CODE_DIR_OPTION, str(code_dir)])
    return command


def _stop_process(process: subprocess.Popen[Any]) -> None:
    """Terminate a child process and force it down if necessary."""
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def publish_form(  # noqa: PLR0913, PLR0917
    form_path: Path,
    host: str,
    port: int,
    signaling: str,
    pin: str | None,
    ephemeral: bool,
    db_dir: Path | None = None,
    database_name: str | None = None,
    code_dir: Path | None = None,
) -> None:
    """Run textual-serve locally and expose it through bitbang."""
    ensure_ca_store()
    command = build_serve_command(
        form_path,
        host,
        port,
        db_dir,
        database_name,
        code_dir,
    )
    serve_process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_server(host, port)
        target = f"{host}:{port}"
        adapter = BitBangWSGI(
            RewritingProxy(target),
            program_name=BITBANG_PROGRAM_NAME,
            server=signaling,
            pin=pin,
            ephemeral=ephemeral,
        )
        adapter.ws_target = target
        adapter.run()
    finally:
        _stop_process(serve_process)
