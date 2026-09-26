"""Expose the existing health ping as one remote MCP Streamable HTTP tool."""

from __future__ import annotations

import contextlib
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from a2wsgi import WSGIMiddleware
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Mount

from app import app as reality_app


PING_URL = "https://xiaxia-sense-server.onrender.com/ping"
PUBLIC_HOST = "xiaxia-sense-server.onrender.com"
MCP_SERVER = MCPServer("xiaxia-reality-health")


@MCP_SERVER.tool(name="getSenseHealth")
def get_sense_health() -> dict[str, Any]:
    """Read and return the existing Xiaxia Reality server health JSON."""
    try:
        with urlopen(Request(PING_URL, method="GET"), timeout=20) as response:
            if not 200 <= response.status < 300:
                raise ValueError(f"Reality returned HTTP {response.status}")
            data = json.load(response)
    except HTTPError as error:
        raise ValueError(f"Reality returned HTTP {error.code}") from error
    except URLError as error:
        raise ValueError(f"Reality network error: {error.reason}") from error
    except (TimeoutError, OSError) as error:
        raise ValueError(f"Reality network error: {error}") from error
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Reality returned invalid JSON: {error}") from error

    if not isinstance(data, dict):
        raise ValueError("Reality returned unexpected JSON")
    return data


@contextlib.asynccontextmanager
async def lifespan(_app: Starlette):
    async with MCP_SERVER.session_manager.run():
        yield


MCP_ASGI_APP = MCP_SERVER.streamable_http_app(
    streamable_http_path="/mcp",
    json_response=True,
    transport_security=TransportSecuritySettings(
        allowed_hosts=[PUBLIC_HOST, f"{PUBLIC_HOST}:*"]
    ),
)

app = Starlette(
    routes=[*MCP_ASGI_APP.routes, Mount("/", app=WSGIMiddleware(reality_app))],
    lifespan=lifespan,
)
