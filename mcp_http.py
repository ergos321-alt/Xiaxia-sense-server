"""Expose the existing health ping as one remote MCP Streamable HTTP tool."""

from __future__ import annotations

import contextlib
import json
from typing import Annotated, Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from a2wsgi import WSGIMiddleware
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, ConfigDict, Field
from starlette.applications import Starlette
from starlette.routing import Mount

from app import SENSE_TOKEN, app as reality_app


PING_URL = "https://xiaxia-sense-server.onrender.com/ping"
REALITY_BASE_URL = "https://xiaxia-sense-server.onrender.com"
REALITY_STATUS_URL = "https://xiaxia-sense-server.onrender.com/reality/status"
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


@MCP_SERVER.tool(name="getRealityStatus")
def get_reality_status() -> dict[str, Any]:
    """Read the existing authenticated Reality sensor and service status."""
    if not SENSE_TOKEN:
        raise ValueError("Reality Bearer authentication is not configured")

    request = Request(
        REALITY_STATUS_URL,
        headers={"Authorization": f"Bearer {SENSE_TOKEN}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=20) as response:
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


def _request_reality(
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Forward one existing Reality operation with its existing Bearer auth."""
    if not SENSE_TOKEN:
        raise ValueError("Reality Bearer authentication is not configured")

    url = f"{REALITY_BASE_URL}{path}"
    if query:
        encoded_query = {
            key: str(value).lower() if isinstance(value, bool) else value
            for key, value in query.items()
            if value is not None
        }
        if encoded_query:
            url = f"{url}?{urlencode(encoded_query, doseq=True)}"

    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Authorization": f"Bearer {SENSE_TOKEN}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)

    try:
        with urlopen(request, timeout=20) as response:
            if not 200 <= response.status < 300:
                raise ValueError(f"Reality returned HTTP {response.status}")
            result = json.load(response)
    except HTTPError as error:
        try:
            error_body = json.loads(error.read().decode("utf-8"))
            detail = json.dumps(error_body, ensure_ascii=False)
        except (UnicodeError, json.JSONDecodeError):
            detail = ""
        message = f"Reality returned HTTP {error.code}"
        if detail:
            message = f"{message}: {detail}"
        raise ValueError(message) from error
    except URLError as error:
        raise ValueError(f"Reality network error: {error.reason}") from error
    except (TimeoutError, OSError) as error:
        raise ValueError(f"Reality network error: {error}") from error
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Reality returned invalid JSON: {error}") from error

    if not isinstance(result, dict):
        raise ValueError("Reality returned unexpected JSON")
    return result


@MCP_SERVER.tool(name="getFullSenseContext")
def get_full_sense_context() -> dict[str, Any]:
    """Read the complete existing sensor and interpreted context."""
    return _request_reality("GET", "/context")


@MCP_SERVER.tool(name="getRealityContext")
def get_reality_context() -> dict[str, Any]:
    """Read the existing complete Reality context."""
    return _request_reality("GET", "/reality/context")


@MCP_SERVER.tool(name="getRealitySummary")
def get_reality_summary() -> dict[str, Any]:
    """Read the existing compact Reality and Phone summaries."""
    return _request_reality("GET", "/reality/summary")


@MCP_SERVER.tool(name="getRealityEnvironment")
def get_reality_environment() -> dict[str, Any]:
    """Read the existing environment and weather Reality data."""
    return _request_reality("GET", "/reality/environment")


@MCP_SERVER.tool(name="getRealityDevice")
def get_reality_device() -> dict[str, Any]:
    """Read the existing device power and network Reality data."""
    return _request_reality("GET", "/reality/device")


@MCP_SERVER.tool(name="getRealityLocation")
def get_reality_location() -> dict[str, Any]:
    """Read the existing location and mobility Reality data."""
    return _request_reality("GET", "/reality/location")


@MCP_SERVER.tool(name="getPhoneActivity")
def get_phone_activity() -> dict[str, Any]:
    """Read the existing current Phone Activity."""
    return _request_reality("GET", "/reality/phone")


@MCP_SERVER.tool(name="getPhoneTimeline")
def get_phone_timeline(
    minutes: Annotated[int, Field(ge=1, le=2880)] = 60,
    limit: Annotated[int, Field(ge=1, le=1000)] = 200,
) -> dict[str, Any]:
    """Read the recent Phone Activity timeline."""
    return _request_reality(
        "GET", "/reality/phone/timeline", query={"minutes": minutes, "limit": limit}
    )


@MCP_SERVER.tool(name="getPhoneHistory")
def get_phone_history(
    minutes: Annotated[int, Field(ge=1, le=2880)] = 60,
    start: Annotated[str, Field(json_schema_extra={"format": "date-time"})]
    | None = None,
    end: Annotated[str, Field(json_schema_extra={"format": "date-time"})]
    | None = None,
    types: str = "all",
    include_timeline: bool = False,
    timeline_limit: Annotated[int, Field(ge=1, le=1000)] = 200,
) -> dict[str, Any]:
    """Read summarized short-term Phone Activity history."""
    return _request_reality(
        "GET",
        "/reality/phone/history",
        query={
            "minutes": minutes,
            "start": start,
            "end": end,
            "types": types,
            "include_timeline": include_timeline,
            "timeline_limit": timeline_limit,
        },
    )


@MCP_SERVER.tool(name="getSpatialReality")
def get_spatial_reality() -> dict[str, Any]:
    """Read the existing current Spatial Reality."""
    return _request_reality("GET", "/reality/spatial")


@MCP_SERVER.tool(name="getSpatialHistory")
def get_spatial_history(
    minutes: Annotated[int, Field(ge=1, le=2880)] = 30,
) -> dict[str, Any]:
    """Read recent location history and movement analysis."""
    return _request_reality(
        "GET", "/reality/spatial/history", query={"minutes": minutes}
    )


@MCP_SERVER.tool(name="findNearbyPlaces")
def find_nearby_places(
    keywords: str | None = None,
    types: str | None = None,
    radius: Annotated[int, Field(ge=1)] = 1000,
) -> dict[str, Any]:
    """Search the existing nearby Amap POI operation."""
    return _request_reality(
        "GET",
        "/reality/spatial/nearby",
        query={"keywords": keywords, "types": types, "radius": radius},
    )


@MCP_SERVER.tool(name="getSpatialRoute")
def get_spatial_route(
    mode: Literal["walking", "driving", "cycling", "electrobike"] = "walking",
    place: str | None = None,
    poi_location: str | None = None,
    poi_name: str | None = None,
    latitude: Annotated[float, Field(ge=-90, le=90)] | None = None,
    longitude: Annotated[float, Field(ge=-180, le=180)] | None = None,
) -> dict[str, Any]:
    """Plan a route using the existing Reality Spatial route operation."""
    return _request_reality(
        "GET",
        "/reality/spatial/route",
        query={
            "mode": mode,
            "place": place,
            "poi_location": poi_location,
            "poi_name": poi_name,
            "latitude": latitude,
            "longitude": longitude,
        },
    )


@MCP_SERVER.tool(name="listPersonalPlaces")
def list_personal_places() -> dict[str, Any]:
    """List the existing saved personal places."""
    return _request_reality("GET", "/reality/spatial/places")


@MCP_SERVER.tool(name="savePersonalPlace")
def save_personal_place(
    name: Annotated[str, Field(min_length=1)],
    kind: str = "custom",
    latitude: Annotated[float, Field(ge=-90, le=90)] | None = None,
    longitude: Annotated[float, Field(ge=-180, le=180)] | None = None,
    radius_m: Annotated[float, Field(gt=0)] = 150,
    note: str | None = None,
    use_current_location: bool | None = None,
) -> dict[str, Any]:
    """Save a personal place through the existing Reality operation."""
    body = {
        key: value
        for key, value in {
            "name": name,
            "kind": kind,
            "latitude": latitude,
            "longitude": longitude,
            "radius_m": radius_m,
            "note": note,
            "use_current_location": use_current_location,
        }.items()
        if value is not None
    }
    return _request_reality("POST", "/reality/spatial/places", body=body)


class PersonalPlacePoi(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str | None = None
    type: str | None = None
    address: str | None = None
    location: str | None = None


@MCP_SERVER.tool(name="savePersonalPlaceFromPoi")
def save_personal_place_from_poi(
    name: str | None = None,
    poi_name: str | None = None,
    poi_location: str | None = None,
    poi_type: str | None = None,
    poi_address: str | None = None,
    poi_id: str | None = None,
    kind: str = "custom",
    radius_m: Annotated[float, Field(gt=0)] = 150,
    note: str | None = None,
    poi: PersonalPlacePoi | None = None,
) -> dict[str, Any]:
    """Save an Amap POI as a personal place through the existing operation."""
    body = {
        key: value.model_dump(exclude_none=True) if isinstance(value, BaseModel) else value
        for key, value in {
            "name": name,
            "poi_name": poi_name,
            "poi_location": poi_location,
            "poi_type": poi_type,
            "poi_address": poi_address,
            "poi_id": poi_id,
            "kind": kind,
            "radius_m": radius_m,
            "note": note,
            "poi": poi,
        }.items()
        if value is not None
    }
    return _request_reality(
        "POST", "/reality/spatial/places/from-poi", body=body
    )


@MCP_SERVER.tool(name="getPersonalPlace")
def get_personal_place(name: str) -> dict[str, Any]:
    """Read one existing personal place by its name."""
    return _request_reality(
        "GET", f"/reality/spatial/places/{quote(name, safe='')}"
    )


@MCP_SERVER.tool(name="deletePersonalPlace")
def delete_personal_place(name: str) -> dict[str, Any]:
    """Delete a saved personal place through the existing Reality operation."""
    return _request_reality(
        "DELETE", f"/reality/spatial/places/{quote(name, safe='')}"
    )


class HandCommandParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["on", "off"] | None = None
    stream: Literal["media"] | None = None
    level: Annotated[int, Field(ge=0, le=100)] | None = None
    app: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    duration_seconds: Annotated[int, Field(ge=1, le=604800)] | None = None
    label: Annotated[str, Field(max_length=200)] | None = None
    time: Annotated[str, Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")] | None = None
    destination: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    latitude: Annotated[float, Field(ge=-90, le=90)] | None = None
    longitude: Annotated[float, Field(ge=-180, le=180)] | None = None
    place_id: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    travel_mode: Literal["walking", "driving", "cycling", "electrobike"] | None = None


@MCP_SERVER.tool(name="createHandCommand")
def create_hand_command(
    action: Literal[
        "flashlight",
        "volume",
        "open_app",
        "timer",
        "alarm",
        "do_not_disturb",
        "battery_saver",
        "navigation",
    ],
    parameters: HandCommandParameters,
) -> dict[str, Any]:
    """Persist a validated Android action command that Tasker may execute on-device."""
    return _request_reality(
        "POST",
        "/hand/commands",
        body={
            "action": action,
            "parameters": parameters.model_dump(exclude_none=True),
        },
    )


@MCP_SERVER.tool(name="getHandCommandStatus")
def get_hand_command_status(command_id: str) -> dict[str, Any]:
    """Read the existing status of one Hand command."""
    return _request_reality(
        "GET", f"/hand/commands/{quote(command_id, safe='')}"
    )


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
