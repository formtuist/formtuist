"""Define textual-serve wrapper for serving forms over the web."""

from pathlib import Path
from typing import Any

import aiohttp_jinja2
from aiohttp import web
from textual_serve.server import Server, to_int

# favicon image shipped with the package and its URL path
FAVICON_FILENAME = "Formtuist-Icon.png"
FAVICON_URL_PATH = "/favicon.png"


class FormtuistServer(Server):
    """A textual-serve Server that serves a favicon and request-host URLs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Store the favicon path and delegate to the base Server."""
        self._favicon_path = (
            Path(__file__).parent / "templates" / FAVICON_FILENAME
        )
        super().__init__(*args, **kwargs)

    @aiohttp_jinja2.template("app_index.html")
    async def handle_index(self, request: web.Request) -> dict[str, Any]:
        """Serve the HTML with URLs built from the request host.

        The base server derives the WebSocket and static URLs from the bind
        address (0.0.0.0 by default), which browsers such as Firefox refuse
        to connect to. Deriving them from the request host keeps the page
        consistent with the address the browser actually used, so localhost
        and named hosts both work without passing a specific --host.
        """
        router = request.app.router

        def get_url(route: str, **args: Any) -> str:
            """Return an absolute http(s) URL using the request host."""
            path = router[route].url_for(**args)
            return f"{request.scheme}://{request.host}{path}"

        def get_websocket_url(route: str, **args: Any) -> str:
            """Return a ws(s) URL using the request host."""
            path = router[route].url_for(**args)
            scheme = "wss" if request.scheme == "https" else "ws"
            return f"{scheme}://{request.host}{path}"

        context: dict[str, Any] = {
            "font_size": to_int(request.query.get("fontsize", "16"), 16),
            "app_websocket_url": get_websocket_url("websocket"),
        }
        context["config"] = {
            "static": {
                "url": get_url("static", filename="/").rstrip("/") + "/",
            },
        }
        context["application"] = {"name": self.title}
        return context

    async def _handle_favicon(self, _request: web.Request) -> web.FileResponse:
        """Serve the favicon image file."""
        return web.FileResponse(self._favicon_path)

    async def _make_app(self) -> web.Application:
        """Add the favicon route to the aiohttp application."""
        app = await super()._make_app()
        app.router.add_get(FAVICON_URL_PATH, self._handle_favicon)
        return app
