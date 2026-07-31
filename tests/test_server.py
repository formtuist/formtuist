"""Tests for the formtuitous textual-serve server wrapper."""

import asyncio
from pathlib import Path

from formtuitous.server import (
    FAVICON_FILENAME,
    FAVICON_URL_PATH,
    FormtuitousServer,
)


class TestFormtuitousServer:
    """Tests for the FormtuitousServer wrapper."""

    def test_favicon_file_exists(self) -> None:
        """The favicon image ships with the package."""
        favicon = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "formtuitous"
            / "templates"
            / FAVICON_FILENAME
        )
        assert favicon.is_file()

    def test_favicon_route_registered(self) -> None:
        """_make_app registers the favicon route."""
        server = FormtuitousServer("echo hello", port=8123)

        async def run() -> None:
            app = await server._make_app()
            routes = {
                route.resource.canonical
                for route in app.router.routes()
                if route.resource is not None
            }
            assert FAVICON_URL_PATH in routes

        asyncio.run(run())
