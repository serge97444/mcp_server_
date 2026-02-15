from typing import Any, Dict ,Union,List
import httpx , requests
from mcp.server.fastmcp import FastMCP
import dotenv
from pydantic import BaseModel , Field,ValidationError, ConfigDict
from mcp.server.transport_security import TransportSecuritySettings
import os 
import mcp.types as types

openai_api_key = dotenv.load_dotenv("../")

ASSETS_DIR= "./Assets"
TOOL_NAME = "Call_Life_Insurance_Tariff"

WIDGET_TEMPLATE_URI="ui://widget/formulaire.html"
WIDGET_TITLE="Please fill in the form to get your tariff"
WIDGET_INVOKING= "Preparing your tariff and conditions"
WIDGET_INVOKED="Here is the tariff and your conditions"
MIME_TYPE="text/html+skybridge"

def _split_env_list(value: str | None) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _transport_security_settings() -> TransportSecuritySettings:
    allowed_hosts = _split_env_list(os.getenv("MCP_ALLOWED_HOSTS"))
    allowed_origins = _split_env_list(os.getenv("MCP_ALLOWED_ORIGINS"))
    if not allowed_hosts and not allowed_origins:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def _load_widget_html()->str:
    html_path = ASSETS_DIR / "formulaire.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf8")
    
    fallback = sorted(ASSETS_DIR.glob("formulaire*.html"))

    if fallback:
        return fallback[-1].read_text(encoding="utf8")
    

    raise FileNotFoundError(
        f'Widget HTML for "Life Insurance" not found in {ASSETS_DIR}. '
        "Run `pnpm run build` to generate the assets before starting the server."
    )

LIFE_INSURANCE_HTML = _load_widget_html()

def _widget_meta()->Dict[str,Any]:
    return {
        "openai/outputTemplate" : WIDGET_TEMPLATE_URI,
        "openai/toolInvocation/invoking" : WIDGET_INVOKING,
        "openai/toolInvocation/invoked": WIDGET_INVOKED,
        "openai/widgetAccessible": True
    }

class User(BaseModel):
    age : int
    versement_initial : float
    duree_investissment : int
    niveau_risque : int

TOOL_INPUT_SCHEMA = User.model_json_schema(by_alias=True)

mcp =FastMCP("Draft_LI",
             stateless_http=True,
    transport_security=_transport_security_settings(),)

@mcp._mcp_server.list_tools()
async def _list_tools()->List[types.Tool]:
    """A function listing all available tools

    Returns:
        List[types.Tool]: all the tools the MCP server provides
    """
    return [
        types.Tool(
            name = TOOL_NAME,
            title = "Call Life Insurance tool",
            description="Calls a life insurance engine to retrieve the price and conditions",
            input_schema = TOOL_INPUT_SCHEMA,
            _meta = _widget_meta()
        )
    ]

@mcp._mcp_server.list_resources()
async def _list_resources()->List[types.Resource]:
    return [
        types.Resource(
            name=WIDGET_TITLE,
            title=WIDGET_TITLE,
            uri=WIDGET_TEMPLATE_URI,
            description="Conditions and offer of the life insurance",
            mimeType=MIME_TYPE,
            _meta = _widget_meta(),
        )
    ]

async def _handle_read_resource(req : types.ReadResourceRequest)->types.ServerResult:
    if str(req.params.uri) != WIDGET_TEMPLATE_URI:
        return types.ServerResult(
            types.ReadResourceResult(contents=[],
            _meta = {"error" : f"Unknown resource : {req.params.uri}"},))
    else:
        contents = [types.TextResourceContents(
            uri =WIDGET_TEMPLATE_URI,
            mimeType = MIME_TYPE,
            text=LIFE_INSURANCE_HTML,
            _meta=_widget_meta()
                                               )]
    return types.ServerResult(types.ReadResourceResult(contents=contents))

async def _handle_call_tool(req:types.CallToolRequest)->types.ServerResult:
    if req.params.name != TOOL_NAME:
        return types.ServerResult(
            types.CallToolResult(
                content=[types.TextContent(
                    type="text",
                    text=f"Unknown tool : {req.params.name}"
                )] , isError = True,
            )
        )
    try:
        payload=User.model_validate(req.params.name or {})
    except ValidationError as exc:
            return types.ServerResult(
                types.CallToolResult(
                    content=[
                        types.TextContent(
                            type="text",
                            text=f"Invalid input : {exc.errors()}"
                        )
                    ],
                    isError = True,
                )
            )
    
    
    
