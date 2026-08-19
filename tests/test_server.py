"""Tests for the formtuist textual-serve server wrapper."""

import asyncio
from pathlib import Path

import pytest
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from formtuist.server import (
    FAVICON_FILENAME,
    FAVICON_URL_PATH,
    FormtuistServer,
)

# the custom HTML template served to browsers for the web interface
TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "formtuist"
    / "templates"
    / "app_index.html"
)


class TestFormtuistServer:
    """Tests for the FormtuistServer wrapper."""

    def test_favicon_file_exists(self) -> None:
        """The favicon image ships with the package."""
        favicon = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "formtuist"
            / "templates"
            / FAVICON_FILENAME
        )
        assert favicon.is_file()

    def test_favicon_route_registered(self) -> None:
        """_make_app registers the favicon route."""
        server = FormtuistServer("echo hello", port=8123)

        async def run() -> None:
            app = await server._make_app()
            routes = {
                route.resource.canonical
                for route in app.router.routes()
                if route.resource is not None
            }
            assert FAVICON_URL_PATH in routes

        asyncio.run(run())

    def test_index_uses_relative_urls(self) -> None:
        """The served websocket and static URLs are origin-relative."""
        server = FormtuistServer("echo hello", host="0.0.0.0", port=8124)

        async def run() -> None:
            app = await server._make_app()
            async with TestServer(app) as test_server:
                async with ClientSession(raise_for_status=True) as session:
                    async with session.get(test_server.make_url("/")) as resp:
                        text = await resp.text()
            assert "0.0.0.0" not in text
            assert 'data-session-websocket-url="/ws"' in text
            assert 'href="/static/css/xterm.css"' in text
            assert "http://127.0.0.1" not in text

        asyncio.run(run())

    def test_quiet_startup_suppresses_banner(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A FormtuistServer prints no banner on startup by default."""
        server = FormtuistServer("echo hello", host="0.0.0.0", port=8125)

        async def run() -> None:
            app = await server._make_app()
            async with TestServer(app) as test_server:
                async with ClientSession(raise_for_status=True) as session:
                    async with session.get(test_server.make_url("/")) as resp:
                        await resp.text()

        asyncio.run(run())
        out = capsys.readouterr().out
        assert "Serving" not in out
        assert "Press Ctrl+C" not in out
        assert "echo hello" not in out


class TestAppIndexTemplate:
    """Tests that the served HTML template is well-formed."""

    def test_no_stray_markup_in_head(self) -> None:
        """The head contains no leftover SVG element fragments."""
        raw = TEMPLATE_PATH.read_text(encoding="utf-8")
        head = raw[: raw.index("</head>")]
        assert "<rect" not in head.lower()
        assert "</svg>" not in head.lower()

    def test_head_closes_before_body(self) -> None:
        """Styles and scripts stay in the head, ahead of the body."""
        raw = TEMPLATE_PATH.read_text(encoding="utf-8")
        assert raw.index("</head>") < raw.index("<body")

    def test_favicon_link_present_in_head(self) -> None:
        """The favicon link is served from the template head."""
        raw = TEMPLATE_PATH.read_text(encoding="utf-8")
        head = raw[: raw.index("</head>")]
        assert 'rel="icon"' in head
        assert "/favicon.png" in head

    def test_terminal_div_in_body(self) -> None:
        """The terminal element lives directly in the body."""
        raw = TEMPLATE_PATH.read_text(encoding="utf-8")
        body = raw[raw.index("<body") :]
        assert 'id="terminal"' in body
