from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import json

from pydantic import BaseModel, ValidationError
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
import mcp.types as types

ASSETS_DIR = Path(__file__).parent / "assets"
CONDITIONS_PATH = Path(__file__).parent / "conditions_generales.txt"

TOOL_NAME = "Call_Life_Insurance_Tariff"
WIDGET_TEMPLATE_URI = "ui://widget/formulaire.html"
WIDGET_TITLE = "Votre tarif assurance vie"
WIDGET_INVOKING = "Calcul de votre tarif et preparation des conditions"
WIDGET_INVOKED = "Voici votre tarif et vos conditions"
MIME_TYPE = "text/html+skybridge"


def _split_env_list(value: str | None) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _transport_security_settings() -> TransportSecuritySettings:
    allowed_hosts = _split_env_list(
        __import__("os").getenv("MCP_ALLOWED_HOSTS")
    )
    allowed_origins = _split_env_list(
        __import__("os").getenv("MCP_ALLOWED_ORIGINS")
    )
    if not allowed_hosts and not allowed_origins:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def _load_widget_template() -> str:
    html_path = ASSETS_DIR / "formulaire.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf8")
    raise FileNotFoundError(f"Template not found: {html_path}")


TEMPLATE_HTML = _load_widget_template()
CONDITIONS_TEXT = CONDITIONS_PATH.read_text(encoding="utf8")


class User(BaseModel):
    age: int
    versement_initial: float
    duree_investissment: int
    niveau_risque: int


TOOL_INPUT_SCHEMA = User.model_json_schema(by_alias=True)

mcp = FastMCP(
    "LifeInsurance_ClientSide_React",
    stateless_http=True,
    transport_security=_transport_security_settings(),
)


def _widget_meta() -> Dict[str, Any]:
    return {
        "openai/outputTemplate": WIDGET_TEMPLATE_URI,
        "openai/toolInvocation/invoking": WIDGET_INVOKING,
        "openai/toolInvocation/invoked": WIDGET_INVOKED,
        "openai/widgetAccessible": True,
    }


def compute_premium(user: User) -> float:
    base = 20.0
    age_factor = max(user.age - 30, 0) * 0.7
    risk_factor = user.niveau_risque * 5.0
    duration_factor = user.duree_investissment * 2.0
    initial_discount = min(user.versement_initial / 10000.0, 5.0)
    premium = base + age_factor + risk_factor + duration_factor - initial_discount
    return max(premium, 15.0)


def _inject_react_data(data: Dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    payload = payload.replace("</", "<\\/")
    return TEMPLATE_HTML.replace("__APP_DATA__", payload)


@mcp._mcp_server.list_tools()
async def _list_tools() -> List[types.Tool]:
    return [
        types.Tool(
            name=TOOL_NAME,
            title="Calcul du tarif assurance vie",
            description="Calcule un tarif a partir d'un profil client",
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
            description="Affichage du tarif et des conditions",
            mimeType=MIME_TYPE,
            _meta=_widget_meta(),
        )
    ]


@mcp._mcp_server.read_resource()
async def _handle_read_resource(
    req: types.ReadResourceRequest,
) -> types.ServerResult:
    if str(req.params.uri) != WIDGET_TEMPLATE_URI:
        return types.ServerResult(
            types.ReadResourceResult(
                contents=[],
                _meta={"error": f"Unknown resource: {req.params.uri}"},
            )
        )

    contents = [
        types.TextResourceContents(
            uri=WIDGET_TEMPLATE_URI,
            mimeType=MIME_TYPE,
            text=TEMPLATE_HTML,
            _meta=_widget_meta(),
        )
    ]
    return types.ServerResult(types.ReadResourceResult(contents=contents))


@mcp._mcp_server.call_tool()
async def _handle_call_tool(
    req: types.CallToolRequest,
) -> types.ServerResult:
    if req.params.name != TOOL_NAME:
        return types.ServerResult(
            types.CallToolResult(
                content=[
                    types.TextContent(type="text", text=f"Unknown tool: {req.params.name}")
                ],
                isError=True,
            )
        )

    try:
        payload = User.model_validate(req.params.arguments or {})
    except ValidationError as exc:
        return types.ServerResult(
            types.CallToolResult(
                content=[
                    types.TextContent(type="text", text=f"Invalid input: {exc.errors()}")
                ],
                isError=True,
            )
        )

    premium = compute_premium(payload)
    data = {
        "age": payload.age,
        "versement_initial": f"{payload.versement_initial:,.2f}".replace(",", " "),
        "duree_investissment": payload.duree_investissment,
        "niveau_risque": payload.niveau_risque,
        "premium": f"{premium:,.2f}".replace(",", " "),
        "conditions_generales": CONDITIONS_TEXT,
    }

    html_out = _inject_react_data(data)

    return types.ServerResult(
        types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text="Tarif calcule avec succes.",
                )
            ],
            _meta={
                "openai/outputTemplate": WIDGET_TEMPLATE_URI,
                "openai/output": {
                    "mimeType": MIME_TYPE,
                    "text": html_out,
                },
            },
        )
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("mcp_server:app", host="0.0.0.0", port=8000)
