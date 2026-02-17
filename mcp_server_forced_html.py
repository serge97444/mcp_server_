from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import html
from dataclasses import dataclass
import json
import os
import logging

import numpy as np
from pydantic import BaseModel, ValidationError
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
import mcp.types as types
import random


try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    pass

LOG_LEVEL = os.getenv("MCP_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger("mcp_server_forced_html")

WIDGET_VARIANT = os.getenv("MCP_WIDGET_VARIANT", "minimal").strip().lower()
logger.info("Using widget variant: %s", WIDGET_VARIANT)
ASSETS_DIR = Path(__file__).parent / "Assets" / WIDGET_VARIANT
CONDITIONS_PATH = Path(__file__).parent / "conditions_generales.txt"

TOOL_NAME = "Call_PERI_Simulation"
WIDGET_TEMPLATE_URI = "ui://widget/formulaire-v2.html"
WIDGET_TITLE = "Please provide me the info required to forward a PERI simulation and provide you with our conditions"
WIDGET_INVOKING = "Preparing your simulations and conditions"
WIDGET_INVOKED = "Here is your simulation and your conditions"
MIME_TYPE = "text/html+skybridge"


def _split_env_list(value: str | None) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _transport_security_settings() -> TransportSecuritySettings:
    allowed_hosts = _split_env_list(__import__("os").getenv("MCP_ALLOWED_HOSTS"))
    allowed_origins = _split_env_list(__import__("os").getenv("MCP_ALLOWED_ORIGINS"))
    if not allowed_hosts and not allowed_origins:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def _load_widget_html() -> str:
    html_path = ASSETS_DIR / "formulaire.html"
    if html_path.exists():
        logger.info("Loaded widget HTML: %s", html_path)
        return html_path.read_text(encoding="utf8")
    fallback = Path(__file__).parent / "Assets" / "minimal" / "formulaire.html"
    if fallback.exists():
        logger.info("Loaded widget HTML fallback: %s", fallback)
        return fallback.read_text(encoding="utf8")
    raise FileNotFoundError(f"Widget not found: {html_path}")


LIFE_INSURANCE_HTML = _load_widget_html()
CONDITIONS_TEXT = CONDITIONS_PATH.read_text(encoding="utf8")


@dataclass
class ReadResourceContent:
    content: str | bytes
    mime_type: str | None = None
    meta: dict[str, Any] | None = None


class User(BaseModel):
    age: int
    versement_initial: float
    duree_investissment: int
    niveau_risque: int


TOOL_INPUT_SCHEMA = User.model_json_schema(by_alias=True)

mcp = FastMCP(
    "Amazing_Life_Insurance_Company",
    stateless_http=True,
    instructions="A PERI is a life insurance product aiming at capitalizing money for the retirement, "
    "and has multiple fiscal benefits."
    "At the Amazing Life Insurance company , we provide the best one in the market. "
    "If a user asks for a PERI at the Amazing Life Insurance Company please call the tool"
    "Call_PERI_Simulation . You would need to collect the age, the 'durée d'investissement' "
    "(investment duration) ,"
    " , the 'versement initial' (initial amount) , and the 'niveau de risque' "
    "(level of risk wanted , between 1 and 7 "
    ", 1 being the less risky).",
    transport_security=_transport_security_settings(),
)


def _widget_meta() -> Dict[str, Any]:
    # Forced HTML mode: do NOT include openai/outputTemplate here.
    return {
        "openai/toolInvocation/invoking": WIDGET_INVOKING,
        "openai/toolInvocation/invoked": WIDGET_INVOKED,
        "openai/widgetAccessible": True,
    }


@mcp._mcp_server.list_tools()
async def _list_tools() -> List[types.Tool]:
    return [
        types.Tool(
            name=TOOL_NAME,
            title="Call Life Insurance PERI Simulation",
            description="Calls a PERI Simulation engine that will provide the overall "
            "gain and condition to a user provided his age, investment duration, level of risk,"
            "and initial amount. Please use overall_gain result in your synthesis to provide an answer",
            inputSchema=TOOL_INPUT_SCHEMA,
            _meta=_widget_meta(),
        )
    ]


@mcp._mcp_server.list_resources()
async def _list_resources() -> List[types.Resource]:
    return [
        types.Resource(
            name=WIDGET_TITLE,
            title=WIDGET_TITLE,
            uri=WIDGET_TEMPLATE_URI,
            description="Conditions and offer of the life insurance PERI product",
            mimeType=MIME_TYPE,
            _meta=_widget_meta(),
        )
    ]


def compute_simulation(user: User, taux: float = 1.02) -> Dict[str, Any]:
    values: List[float] = []
    somme_init = user.versement_initial
    if user.niveau_risque < 3:
        for _ in range(1, user.duree_investissment + 1):
            somme_init *= taux
            values.append(somme_init)
        overall_gain = values[-1] - user.versement_initial if values else 0.0
        x_vals = list(np.linspace(1, user.duree_investissment, len(values)))
        return {"X": x_vals, "Y": values, "overall_gain": overall_gain}
    else:
        for _ in range(1, user.duree_investissment + 1):
            somme_init *= taux * random.gauss(2, 4)
            values.append(somme_init)
        overall_gain = values[-1] - user.versement_initial if values else 0.0
        x_vals = list(np.linspace(1, user.duree_investissment, len(values)))
        return {"X": x_vals, "Y": values, "overall_gain": overall_gain}


def _template_data(user: User, overall_gain: float, conditions: str) -> Dict[str, str]:
    return {
        "age": f"{user.age}",
        "versement_initial": f"{user.versement_initial:,.2f}".replace(",", " "),
        "duree_investissment": f"{user.duree_investissment}",
        "niveau_risque": f"{user.niveau_risque}",
        "overall_gain": f"{overall_gain:,.2f}".replace(",", " "),
        "conditions_generales": conditions,
    }


def _render_html(user: User, overall_gain: float, conditions: str) -> str:
    data = _template_data(user, overall_gain, conditions)
    safe = {k: html.escape(v) for k, v in data.items()}
    html_out = LIFE_INSURANCE_HTML
    for key, value in safe.items():
        html_out = html_out.replace(f"{{{key}}}", value)
    if "__APP_DATA__" in html_out:
        app_data = json.dumps(data, ensure_ascii=False)
        app_data = app_data.replace("</", "<\\/")
        html_out = html_out.replace("__APP_DATA__", app_data)
    return html_out


@mcp._mcp_server.read_resource()
async def _handle_read_resource(uri) -> List[ReadResourceContent]:
    uri_str = str(uri)
    if uri_str != WIDGET_TEMPLATE_URI:
        logger.warning("ReadResourceRequest unknown uri=%s", uri_str)
        return []
    logger.info("ReadResourceRequest uri=%s", uri_str)
    return [
        ReadResourceContent(
            content=LIFE_INSURANCE_HTML,
            mime_type=MIME_TYPE,
            meta=_widget_meta(),
        )
    ]


@mcp._mcp_server.call_tool()
async def _handle_call_tool(name: str, arguments: dict) -> types.CallToolResult:
    logger.info("CallToolRequest name=%s args=%s", name, arguments)
    if name != TOOL_NAME:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Unknown tool: {name}")],
            isError=True,
        )

    try:
        payload = User.model_validate(arguments or {})
    except ValidationError as exc:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Invalid input: {exc.errors()}")],
            isError=True,
        )

    simulation = compute_simulation(payload)
    overall_gain = simulation["overall_gain"]
    html_out = _render_html(payload, overall_gain, CONDITIONS_TEXT)
    logger.info("Rendered HTML length=%s", len(html_out))
    if "{age}" in html_out or "{versement_initial}" in html_out:
        logger.warning("Template placeholders still present in rendered HTML")

    # Forced HTML: provide only the rendered HTML (no outputTemplate).
    return types.CallToolResult(
        content=[types.TextContent(type="text", text="Simulation completed.")],
        _meta={
            "openai/output": {
                "mimeType": MIME_TYPE,
                "text": html_out,
            }
        },
    )


app = mcp.streamable_http_app()

try:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request

    class _RequestLogMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if request.url.path == "/mcp":
                accept = request.headers.get("accept", "")
                content_type = request.headers.get("content-type", "")
                print(
                    f"[mcp] {request.method} {request.url.path} "
                    f"accept={accept!r} content-type={content_type!r}"
                )
            return await call_next(request)

    app.add_middleware(_RequestLogMiddleware)
except Exception:
    pass

try:
    from starlette.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )
except Exception:
    pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
