"""Tests for publishing forms through bitbang."""

import io
import os
import subprocess
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from formtuist import publisher

TARGET = "127.0.0.1:8000"
FORM_PATH = Path("form.json")
HOST = "127.0.0.1"
PORT = 8000


class FakeResponse:
    """Provide the response methods used by the proxy."""

    def __init__(
        self,
        data: bytes = b"body",
        status: int = 200,
        reason: str = "OK",
        content_type: str = "text/plain",
    ) -> None:
        """Store response metadata and body bytes."""
        self.data = data
        self.status = status
        self.reason = reason
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(data)),
            "ETag": "test-etag",
        }
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        """Return the complete body on the first read."""
        if not self.data:
            return b""
        data = self.data
        self.data = b""
        return data if size != 0 else b""

    def close(self) -> None:
        """Record that the response was closed."""
        self.closed = True


class TestRewritingProxy:
    """Tests for the HTTP proxy used by the bitbang adapter."""

    def test_init_adds_http_scheme(self) -> None:
        """Proxy targets without a scheme receive an HTTP scheme."""
        proxy = publisher.RewritingProxy(TARGET)
        assert proxy.target == f"http://{TARGET}"

    def test_init_strips_trailing_slash(self) -> None:
        """Proxy targets retain their scheme without trailing slashes."""
        proxy = publisher.RewritingProxy(f"http://{TARGET}/")
        assert proxy.target == f"http://{TARGET}"

    def test_html_is_rewritten_and_content_length_recomputed(self) -> None:
        """HTML absolute local URLs become origin-relative URLs."""
        html = (
            f"<script src='http://{TARGET}/static/app.js'></script>".encode()
        )
        response = FakeResponse(html, content_type="text/html; charset=utf-8")
        start_response = MagicMock()
        proxy = publisher.RewritingProxy(TARGET)
        with patch(
            "formtuist.publisher.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            body = b"".join(
                proxy(
                    {
                        "REQUEST_METHOD": "GET",
                        "PATH_INFO": "/",
                        "QUERY_STRING": "x=1",
                        "HTTP_ACCEPT_ENCODING": "identity",
                    },
                    start_response,
                )
            )
        request = urlopen.call_args.args[0]
        assert request.full_url == f"http://{TARGET}/?x=1"
        assert body == b"<script src='/static/app.js'></script>"
        headers = start_response.call_args.args[1]
        assert ("Content-Length", str(len(body))) in headers
        assert ("ETag", "test-etag") not in headers
        assert response.closed

    def test_compresses_accepted_compressible_response(self) -> None:
        """Compressible responses use gzip when it makes them smaller."""
        data = b"a" * (publisher.GZIP_MIN_SIZE + 100)
        response = FakeResponse(data, content_type="application/javascript")
        start_response = MagicMock()
        proxy = publisher.RewritingProxy(TARGET)
        with patch(
            "formtuist.publisher.urllib.request.urlopen",
            return_value=response,
        ):
            body = b"".join(
                proxy(
                    {
                        "REQUEST_METHOD": "GET",
                        "PATH_INFO": "/app.js",
                        "QUERY_STRING": "",
                        "HTTP_ACCEPT_ENCODING": "gzip",
                    },
                    start_response,
                )
            )
        assert len(body) < len(data)
        headers = start_response.call_args.args[1]
        assert ("Content-Encoding", "gzip") in headers

    def test_forwards_request_body_and_content_type(self) -> None:
        """Proxy requests forward content types and non-empty bodies."""
        response = FakeResponse()
        start_response = MagicMock()
        proxy = publisher.RewritingProxy(TARGET)
        with patch(
            "formtuist.publisher.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            list(
                proxy(
                    {
                        "REQUEST_METHOD": "POST",
                        "PATH_INFO": "/submit",
                        "QUERY_STRING": "",
                        "CONTENT_TYPE": "application/json",
                        "CONTENT_LENGTH": "7",
                        "wsgi.input": io.BytesIO(b"payload"),
                    },
                    start_response,
                )
            )
        request = urlopen.call_args.args[0]
        assert request.data == b"payload"
        assert request.headers["Content-type"] == "application/json"

    def test_streams_unbuffered_response(self) -> None:
        """Non-HTML responses stream their upstream body unchanged."""
        response = FakeResponse(b"plain", content_type="image/png")
        start_response = MagicMock()
        proxy = publisher.RewritingProxy(TARGET)
        with patch(
            "formtuist.publisher.urllib.request.urlopen",
            return_value=response,
        ):
            body = b"".join(
                proxy(
                    {
                        "REQUEST_METHOD": "GET",
                        "PATH_INFO": "/image.png",
                        "QUERY_STRING": "",
                    },
                    start_response,
                )
            )
        assert body == b"plain"
        start_response.assert_called_once_with(
            "200 OK", list(response.headers.items())
        )

    def test_does_not_compress_when_gzip_is_larger(self) -> None:
        """Gzip is skipped when compression would increase the body size."""
        data = os.urandom(publisher.GZIP_MIN_SIZE + 100)
        response = FakeResponse(data, content_type="application/javascript")
        start_response = MagicMock()
        proxy = publisher.RewritingProxy(TARGET)
        with patch(
            "formtuist.publisher.urllib.request.urlopen",
            return_value=response,
        ):
            body = b"".join(
                proxy(
                    {
                        "REQUEST_METHOD": "GET",
                        "PATH_INFO": "/random.js",
                        "QUERY_STRING": "",
                        "HTTP_ACCEPT_ENCODING": "gzip",
                    },
                    start_response,
                )
            )
        assert body == data
        headers = start_response.call_args.args[1]
        assert ("Content-Encoding", "gzip") not in headers

    def test_forwards_no_body_status(self) -> None:
        """No-body statuses do not buffer or rewrite their response."""
        response = FakeResponse(b"ignored", status=204, reason="No Content")
        start_response = MagicMock()
        proxy = publisher.RewritingProxy(TARGET)
        with patch(
            "formtuist.publisher.urllib.request.urlopen",
            return_value=response,
        ):
            body = b"".join(
                proxy(
                    {
                        "REQUEST_METHOD": "GET",
                        "PATH_INFO": "/health",
                        "QUERY_STRING": "",
                    },
                    start_response,
                )
            )
        assert body == b"ignored"
        assert response.closed

    def test_returns_bad_gateway_for_proxy_error(self) -> None:
        """Upstream connection errors become a WSGI 502 response."""
        start_response = MagicMock()
        proxy = publisher.RewritingProxy(TARGET)
        with patch(
            "formtuist.publisher.urllib.request.urlopen",
            side_effect=OSError("offline"),
        ):
            body = b"".join(
                proxy(
                    {
                        "REQUEST_METHOD": "GET",
                        "PATH_INFO": "/",
                        "QUERY_STRING": "",
                    },
                    start_response,
                )
            )
        assert b"proxy error: offline" in body
        start_response.assert_called_once_with(
            publisher.BAD_GATEWAY_STATUS,
            [("Content-Type", publisher.TEXT_PLAIN_CONTENT_TYPE)],
        )

    def test_handles_http_error_as_upstream_response(self) -> None:
        """HTTP errors preserve the upstream status and error body."""
        error = urllib.error.HTTPError(
            "http://example.test/missing",
            404,
            "Not Found",
            Message(),
            io.BytesIO(b"missing"),
        )
        start_response = MagicMock()
        proxy = publisher.RewritingProxy(TARGET)
        with patch(
            "formtuist.publisher.urllib.request.urlopen",
            side_effect=error,
        ):
            body = b"".join(
                proxy(
                    {
                        "REQUEST_METHOD": "GET",
                        "PATH_INFO": "/missing",
                        "QUERY_STRING": "",
                    },
                    start_response,
                )
            )
        assert body == b"missing"
        assert start_response.call_args.args[0] == "404 Not Found"


class TestPublisherHelpers:
    """Tests for publisher setup and process lifecycle helpers."""

    def test_compressible_content_types(self) -> None:
        """Text and configured media types are compressible."""
        assert publisher._is_compressible("text/css; charset=utf-8")
        assert publisher._is_compressible("image/svg+xml")
        assert not publisher._is_compressible("image/png")

    def test_ensure_ca_store_respects_existing_setting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An existing CA environment setting is not overwritten."""
        custom_ca = "/custom/ca.pem"
        monkeypatch.setenv(publisher.SSL_CERT_FILE, custom_ca)
        publisher.ensure_ca_store()
        assert os.environ[publisher.SSL_CERT_FILE] == custom_ca

    def test_ensure_ca_store_does_nothing_without_candidate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No environment setting is created without a CA candidate."""
        monkeypatch.delenv(publisher.SSL_CERT_FILE, raising=False)
        monkeypatch.delenv(publisher.SSL_CERT_DIR, raising=False)
        monkeypatch.setattr(publisher, "CA_BUNDLE_CANDIDATES", ())
        publisher.ensure_ca_store()
        assert publisher.SSL_CERT_FILE not in os.environ

    def test_ensure_ca_store_uses_candidate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A candidate CA bundle is selected when no setting exists."""
        candidate = tmp_path / "ca.pem"
        candidate.write_text("certificate", encoding="utf-8")
        monkeypatch.delenv(publisher.SSL_CERT_FILE, raising=False)
        monkeypatch.delenv(publisher.SSL_CERT_DIR, raising=False)
        monkeypatch.setattr(publisher, "CA_BUNDLE_CANDIDATES", (candidate,))
        publisher.ensure_ca_store()
        assert os.environ[publisher.SSL_CERT_FILE] == str(candidate)

    def test_build_serve_command_includes_optional_arguments(self) -> None:
        """Child command construction includes all requested options."""
        command = publisher.build_serve_command(
            FORM_PATH,
            HOST,
            PORT,
            Path("db"),
            "responses.db",
            Path("code"),
        )
        assert command[:5] == [
            publisher.sys.executable,
            "-m",
            "formtuist.cli",
            "serve",
            str(FORM_PATH),
        ]
        assert command[-6:] == [
            "--db-dir",
            "db",
            "--database-name",
            "responses.db",
            "--code-dir",
            "code",
        ]

    def test_wait_for_server_returns_when_available(self) -> None:
        """Server readiness polling stops after the first successful request."""
        with patch("formtuist.publisher.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = MagicMock()
            publisher.wait_for_server(HOST, PORT)
        urlopen.assert_called_once()

    def test_wait_for_server_raises_after_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Server readiness polling raises after its deadline."""
        clock = iter((0.0, 0.0, float(publisher.STARTUP_TIMEOUT_SECONDS + 1)))
        monkeypatch.setattr(publisher.time, "monotonic", lambda: next(clock))
        monkeypatch.setattr(publisher.time, "sleep", lambda _seconds: None)
        with patch(
            "formtuist.publisher.urllib.request.urlopen",
            side_effect=OSError("not ready"),
        ):
            with pytest.raises(RuntimeError, match="did not start"):
                publisher.wait_for_server(HOST, PORT)

    def test_publish_form_starts_adapter_and_stops_server(self) -> None:
        """Publishing starts the local server and configures bitbang."""
        process = MagicMock()
        adapter = MagicMock()
        with (
            patch("formtuist.publisher.ensure_ca_store") as ca_store,
            patch(
                "formtuist.publisher.subprocess.Popen", return_value=process
            ) as popen,
            patch("formtuist.publisher.wait_for_server") as wait,
            patch(
                "formtuist.publisher.BitBangWSGI", return_value=adapter
            ) as bitbang,
            patch("formtuist.publisher._stop_process") as stop,
        ):
            publisher.publish_form(
                FORM_PATH,
                HOST,
                PORT,
                "bitba.ng",
                "1234",
                True,
                Path("db"),
                "responses.db",
                Path("code"),
            )
        ca_store.assert_called_once_with()
        popen.assert_called_once()
        wait.assert_called_once_with(HOST, PORT)
        bitbang.assert_called_once()
        assert adapter.ws_target == TARGET
        adapter.run.assert_called_once_with()
        stop.assert_called_once_with(process)

    def test_iter_chunks_closes_after_upstream_error(self) -> None:
        """Streaming cleanup closes a response after a read error."""
        response = MagicMock()
        response.read.side_effect = OSError("stream failed")
        assert list(publisher._iter_chunks(response)) == []
        response.close.assert_called_once_with()

    def test_stop_process_kills_unresponsive_process(self) -> None:
        """Process cleanup kills a child that ignores termination."""
        process = MagicMock()
        process.wait.side_effect = [
            subprocess.TimeoutExpired("formtuist", 5),
            None,
        ]
        publisher._stop_process(process)
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()

    def test_publish_stops_server_when_adapter_fails(self) -> None:
        """Process cleanup runs when bitbang raises an exception."""
        process = MagicMock()
        with (
            patch("formtuist.publisher.ensure_ca_store"),
            patch(
                "formtuist.publisher.subprocess.Popen", return_value=process
            ),
            patch("formtuist.publisher.wait_for_server"),
            patch(
                "formtuist.publisher.BitBangWSGI",
                side_effect=RuntimeError("adapter failed"),
            ),
            patch("formtuist.publisher._stop_process") as stop,
        ):
            with pytest.raises(RuntimeError, match="adapter failed"):
                publisher.publish_form(
                    FORM_PATH, HOST, PORT, "bitba.ng", None, False
                )
        stop.assert_called_once_with(process)
