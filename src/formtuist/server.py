"""Define textual-serve wrapper for serving forms over the web."""

from pathlib import Path
from typing import Any

from aiohttp import web
from textual_serve.server import Server

# favicon image shipped with the package and its URL path
FAVICON_FILENAME = "Formtuist-Icon.png"
FAVICON_URL_PATH = "/favicon.png"


class FormtuistServer(Server):
    """A textual-serve Server that also serves a favicon image."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Store the favicon path and delegate to the base Server."""
        self._favicon_path = (
            Path(__file__).parent / "templates" / FAVICON_FILENAME
        )
        super().__init__(*args, **kwargs)

    async def _handle_favicon(self, _request: web.Request) -> web.FileResponse:
        """Serve the favicon image file."""
        return web.FileResponse(self._favicon_path)

    async def _make_app(self) -> web.Application:
        """Add the favicon route to the aiohttp application."""
        app = await super()._make_app()
        app.router.add_get(FAVICON_URL_PATH, self._handle_favicon)
        return app
