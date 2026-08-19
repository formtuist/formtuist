"""Define textual-serve wrapper for serving forms over the web."""

from pathlib import Path
from typing import Any

import aiohttp_jinja2
from aiohttp import web
from textual_serve.server import LOGO, Server, to_int

# favicon image shipped with the package and its URL path
FAVICON_FILENAME = "Formtuist-Icon.png"
FAVICON_URL_PATH = "/favicon.png"


class FormtuistServer(Server):
    """A textual-serve Server that serves a favicon and request-host URLs."""

    def __init__(self, *args: Any, quiet: bool = True, **kwargs: Any) -> None:
        """Store the favicon path and banner preference, then delegate.

        Quiet by default so programmatic startup and the test suite emit no
        banner output; the serve command opts into the banner via quiet=False.
        """
        self._print_banner = not quiet
        self._favicon_path = (
            Path(__file__).parent / "templates" / FAVICON_FILENAME
        )
        super().__init__(*args, **kwargs)

    async def on_startup(self, app: web.Application) -> None:
        """Print the startup banner only when the serve command asked for it."""
        if self._print_banner:
            self.console.print(LOGO, highlight=False)
            self.console.print(
                f"Serving {self.command!r} on {self.public_url}"
            )
            self.console.print("\n[cyan]Press Ctrl+C to quit")

    @aiohttp_jinja2.template("app_index.html")
    async def handle_index(self, request: web.Request) -> dict[str, Any]:
        """Serve the HTML with relative URLs that resolve at any origin.

        Relative WebSocket and static URLs let the browser connect back to
        whatever origin served the page, so it works for localhost, a named
        host, a NetBird host, and the public bitbang tunnel alike. Bitbang's
        RewritingProxy strips the absolute origin to leave relative paths,
        and its WebSocket bridge forwards the browser's ws request path to
        the local server.
        """
        router = request.app.router
        websocket_path = str(router["websocket"].url_for())
        static_path = str(router["static"].url_for(filename="/"))
        context: dict[str, Any] = {
            "font_size": to_int(request.query.get("fontsize", "16"), 16),
            "app_websocket_url": websocket_path,
        }
        context["config"] = {
            "static": {
                "url": static_path.rstrip("/") + "/",
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
