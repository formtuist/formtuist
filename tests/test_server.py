"""Tests for the formtuist textual-serve server wrapper."""

import asyncio
from pathlib import Path

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
