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
import yaml
import hashlib
#This was done by Serge BEN YAMIN , not AI coded
#-----PARAMETER LOADING
# We load the links for bp and ce simulators
with open('./params.yaml','r') as f:
    data = yaml.safe_load(f)
    link_bp = data["links"]["link_bp"]
    link_ce= data["links"]["link_ce"]

#we load the .env file
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    raise FileNotFoundError("We could not load the .env file")

LOG_LEVEL = os.getenv("MCP_LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("MCP_LOG_FILE", str(Path(__file__).with_name("mcp_server.log")))
WIDGET_DEBUG = os.getenv("MCP_WIDGET_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}

#-----LOGGER SECTION
logger = logging.getLogger("mcp_server")
logger.setLevel(LOG_LEVEL)
#we do not want the stream handler and the logger parent to log stuff in the console
logger.propagate = False

_formatter = logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

#we store the logs in a file
_file_handler = logging.FileHandler(LOG_FILE, encoding="utf8")
_file_handler.setFormatter(_formatter)
_file_handler.setLevel(LOG_LEVEL)
logger.addHandler(_file_handler)

#we add a stream handler to see the logs in the console
_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(_formatter)
_stream_handler.setLevel(LOG_LEVEL)
logger.addHandler(_stream_handler)

#We load different variants, started with on hand html but didn't work even after asking codex to correct my html.
#Then used codex to build a 'rich' UI with React.js
WIDGET_VARIANT = os.getenv("MCP_WIDGET_VARIANT", "rich").strip().lower()
logger.info("Using widget variant: %s", WIDGET_VARIANT)
logger.info("Logging to file: %s", LOG_FILE)
logger.info("Widget debug enabled: %s", WIDGET_DEBUG)

#The static-built html after npm build
ASSETS_DIR = Path(__file__).parent / "Assets" / WIDGET_VARIANT
CONDITIONS_PATH = Path(__file__).parent / "conditions_generales.txt"

#Here we have some variable definitions, we will use a tool called Call_PERI_Simulation to mimic the simulation coming 
#from the PERI . 
TOOL_NAME = "Call_PERI_Simulation"
#This is a virtual URI , when chatgpt  requests that uri , it will loads the resource through the _handle_read_resource function
WIDGET_TEMPLATE_URI = "ui://widget/formulaire-v2.html"
CONDITIONS_GENERALES_URI = "ui://resource/conditions_generales.txt"
#Here are the WIDGET texts at different moments of the loading (début, invocation et fin de simulation)
WIDGET_TITLE = "S'il vous plait apportez moi les informations nécessaires à la constitution de votre simulation" \
" pour le produit PERI afin que je puisse vous donner la projection de vos gains et nos conditions"
WIDGET_INVOKING = "Preparation de votre simulation et de vos conditions"
WIDGET_INVOKED = "Voici votre simulation et vos conditions conditions"
#Openai renders UI through skybridge. It is a special widget format that tells chatgpt to render this HTML as an
#embedded app widget
MIME_TYPE = "text/html+skybridge"


def _split_env_list(value: str | None) -> List[str]:
    """If we have multiple adresses we want them to be splitted in a list
    "url1","url2"-> ["url1","url2"]. This is useful to create a list of MCP Allowed HOST 
    from the env file

    Args:
        value (str | None): the string in the .env file for allowed hosts or origins

    Returns:
        List[str]: a list with allowed hosts or origins
    """
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _transport_security_settings() -> TransportSecuritySettings:
    #for dns rebinding prevention
    allowed_hosts = _split_env_list(__import__("os").getenv("MCP_ALLOWED_HOSTS"))
    #for CORS prevention
    allowed_origins = _split_env_list(__import__("os").getenv("MCP_ALLOWED_ORIGINS"))
    if not allowed_hosts and not allowed_origins:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )

#here we just load one widget, we must load other widgets and rewrite other functions
#or add a router to this one to load other widgets
def _load_peri_simu_widget_html() -> str:
    html_path = ASSETS_DIR / "formulaire.html"
    if html_path.exists():
        logger.info("Loaded widget HTML: %s", html_path)
        return html_path.read_text(encoding="utf8")
    #fallback to the folderwhere we built the html
    fallback = Path(__file__).parent / "Assets" / "rich" / "formulaire.html"
    if fallback.exists():
        logger.info("Loaded widget HTML fallback: %s", fallback)
        return fallback.read_text(encoding="utf8")
    raise FileNotFoundError(f"Widget not found: {html_path}")

#we load the widget and resources
LIFE_INSURANCE_HTML = _load_peri_simu_widget_html()
#this is a 'conditions_generales.txt'
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

#We tell openai client what are our output schema needed in the answer ,and what should be in the input
TOOL_INPUT_SCHEMA = User.model_json_schema(by_alias=True)
TOOL_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "age": {"type": "string"},
        "versement_initial": {"type": "string"},
        "duree_investissment": {"type": "string"},
        "niveau_risque": {"type": "string"},
        "overall_gain": {"type": "string"},
        "conditions_generales": {"type": "string"},
        "link_display": {"type": "string"},
    },
    "required": [
        "age",
        "versement_initial",
        "duree_investissment",
        "niveau_risque",
        "overall_gain",
        "conditions_generales",
        "link_display",
    ],
}

#we start the MCP Server, we put instructions
mcp = FastMCP(
    "Amazing_Life_Insurance_Company",
    #we need stateless as another request can go to another pod and we can scale horizontally
    #no sessions are kept here , each request are independant. If we need to sotre session data we should use external db
    stateless_http=True,
    instructions="A PERI is a life insurance product aiming at capitalizing money for the retirement, "
    "and has multiple fiscal benefits." \
    "At the Amazing Life Insurance company , we provide the best one in the market. " \
    "If a user asks for a PERI at the Amazing Life Insurance Company please call the tool" \
    "Call_PERI_Simulation . You would need to collect the age, the 'durée d'investissement' "
    "(investment duration) ," \
    " , the 'versement initial' (initial amount) , and the 'niveau de risque' "
    "(level of risk wanted , between 1 and 7 " \
    ", 1 being the less risky). " \
    "Always include the link provided by the tool in the final text response (key: link_display). "
    "Do not place that link in the widget output.",
    transport_security=_transport_security_settings(),
)


def _widget_meta() -> Dict[str, Any]:
    """calls meta data : like which resource to invoke

    Returns:
        Dict[str, Any]: all the ui to be invoked and when
    """
    return {
        #points to the virutal ui resource
        "openai/outputTemplate": WIDGET_TEMPLATE_URI,
        #resources when inkoving and invoked
        "openai/toolInvocation/invoking": WIDGET_INVOKING,
        "openai/toolInvocation/invoked": WIDGET_INVOKED,
        #Indicates the widget can be shown/embedded in the chat UI.
        "openai/widgetAccessible": True,
    }


@mcp._mcp_server.list_tools()
async def _list_tools() -> List[types.Tool]:
    """a list tools function to list all the tools available

    Returns:
        List[types.Tool]: a list of tool with descriptions
    """
    return [
        types.Tool(
            name=TOOL_NAME,
            title="Call Life Insurance PERI Simulation",
            description="Calls a PERI Simulation engine that will provide the overall " \
            "gain and condition to a user provided his age, investment duration, level of risk," \
            "and initial amount. The tool returns link_display, which must be mentioned in text "
            "output (not in the widget).",
            inputSchema=TOOL_INPUT_SCHEMA,
            outputSchema=TOOL_OUTPUT_SCHEMA,
            #_widget_meta() is included in list_tools() so the ChatGPT client learns 
            # that this tool is associated with a widget UI.
            _meta=_widget_meta(),
        )
    ]


@mcp._mcp_server.list_resources()
async def _list_resources() -> List[types.Resource]:
    """It list the resources available on the MCP

    Returns:
        List[types.Resource]: _description_
    """
    return [
        #the html resource , the widget displaying peri card
        types.Resource(
            name=WIDGET_TITLE,
            title=WIDGET_TITLE,
            uri=WIDGET_TEMPLATE_URI,
            description="Conditions and offer of the life insurance PERI product",
            mimeType=MIME_TYPE,
            _meta=_widget_meta(),
        ),
        #the conditions generles txt
        types.Resource(name= "CONDITIONS_GENERALES", uri= CONDITIONS_GENERALES_URI,
                       description="The content of the general insurance conditions", mimeType='text/plain')
    ]


@mcp._mcp_server.read_resource()
async def _handle_read_resource(uri : str) -> List[ReadResourceContent]:
    """This functions tells how to read and display the resources

    Args:
        uri (str): the virtual

    Returns:
        List[ReadResourceContent]: a list of resources , either the widget or the text
    """
    uri_str = str(uri)
    #if the uri points to the conditions générales
    if uri_str == CONDITIONS_GENERALES_URI:
        logger.info("ReadResourceRequest uri=%s", uri_str)
        return [ReadResourceContent(content=CONDITIONS_TEXT,mime_type='text/plain')]
    #or the widget 
    elif uri_str == WIDGET_TEMPLATE_URI:
        logger.info("ReadResourceRequest uri=%s", uri_str)
        return [
            ReadResourceContent(
                content=LIFE_INSURANCE_HTML,
                mime_type=MIME_TYPE,
                meta=_widget_meta(),
            )
            ]
    #else we return nothing
    else:
        logger.warning("ReadResourceRequest unknown uri=%s", uri_str)
        return []
    

def compute_simulation(user: User, taux: float = 1.02 ) -> Dict[str, Any]:
    """We simulate a BPCE PERI simulation (this is so Inception !)

    Args:
        user (User): a user info from the chatgpt discussion flow
        taux (float, optional): Bonds rate. Defaults to 1.02.

    Returns:
        Dict[str, Any]: _description_
    """
    values: List[float] = []
    somme_init = user.versement_initial
    #so it's just a basic mechanics , if the risk level is low we invest in "Fonds euros"
    # a steady and safe stream of coupon , and we multiply the investment by the fixed and low rate
    if user.niveau_risque<3:
        for _ in range(1, user.duree_investissment + 1):
            somme_init *= taux
            values.append(somme_init)
        # we compute the gain for the user
        overall_gain = values[-1] - user.versement_initial if values else 0.0
        x_vals = list(np.linspace(1, user.duree_investissment, len(values)))
        return {"X": x_vals, "Y": values, "overall_gain": overall_gain}
    else:
        #else i do the same but i simulate something more spicy like investing in the UC
        # so maybe *2 more gains but *2 more volatilty hence a random gaussian (2,4)
        for _ in range(1, user.duree_investissment + 1):
            somme_init *= taux*random.gauss(2,4)
            values.append(somme_init)
        overall_gain = values[-1] - user.versement_initial if values else 0.0
        x_vals = list(np.linspace(1, user.duree_investissment, len(values)))
        return {"X": x_vals, "Y": values, "overall_gain": overall_gain}


def _template_data(
    user: User, overall_gain: float, conditions: str, link_display: str
) -> Dict[str, str]:
    """This is the input data required to perform the simulation

    Args:
        user (User): a person chatting with the client (chatgpt desktop)
        overall_gain (float): the gain that the user expects if he invests. Comes from the simulation
        conditions (str): The conditions générales, it's like the contract terms
        link_display (str): what link are we going to display (CE  or BP)

    Returns:
        Dict[str, str]: a dictionary with all the required fields as input to the call tool
    """
    return {
        "age": f"{user.age}",
        "versement_initial": f"{user.versement_initial:,.2f}".replace(",", " "),
        "duree_investissment": f"{user.duree_investissment}",
        "niveau_risque": f"{user.niveau_risque}",
        "overall_gain": f"{overall_gain:,.2f}".replace(",", " "),
        "conditions_generales": conditions,
        "link_display": link_display,
    }


def _render_html(
    user: User, overall_gain: float, conditions: str, link_display: str
) -> str:
    """a function to populate and render the html

    Args:
        user (User): the user input class
        overall_gain (float): the overall gains that the user can expcet
        conditions (str): the general conditions strings
        link_display (str): the ce or bp link to display

    Returns:
        str: the html populated
    """
    data = _template_data(user, overall_gain, conditions, link_display)
    safe = {k: html.escape(v) for k, v in data.items()}
    #here we escape (we encode the characters) so no JS code or html can be run is like we encodre < or > or &
    html_out = LIFE_INSURANCE_HTML
    html_out = html_out.replace("__WIDGET_DEBUG__", "true" if WIDGET_DEBUG else "false")
    #we replace the placeholders with their values
    for key, value in safe.items():
        html_out = html_out.replace(f"{{{key}}}", value)
        html_out = html_out.replace(f"{{{{{key}}}}}", value)
    if "__APP_DATA__" in html_out:
        app_data = json.dumps(data, ensure_ascii=False)
        app_data = app_data.replace("</", "<\\/")
        html_out = html_out.replace("__APP_DATA__", app_data)
    return html_out


def _hashbrown_user(user :User , link_bp : str , link_ce : str)-> str:
    key = json.dumps({
            "age": int(user.age),
            "versement_initial": round(float(user.versement_initial), 2),
            "duree_investissment": int(user.duree_investissment),
            "niveau_risque": int(user.niveau_risque),
        },
                          separators=[',',':'],
                          sort_keys = True)
    hash_ = int(hashlib.sha256(key.encode("utf-8")).hexdigest(),16)
    return link_bp if (hash_[0]%2==0) else link_ce



@mcp._mcp_server.call_tool()
async def _handle_call_tool(name: str, arguments: dict) -> types.CallToolResult:
    """function which calls a tool

    Args:
        name (str): the name of the tool called
        arguments (dict): the arguments

    Returns:
        types.CallToolResult: the result of the tool call
    """
    logger.info("CallToolRequest  name=%s arguments=%s",name, arguments)
    if name != TOOL_NAME:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Unknown tool: {name}")],
            isError=True,
        )
    try:
        #do we validate the user requirements in the pydantic class like age etc...
        user= User.model_validate(arguments or {})
        logger.info("payload=%s",str(user))
    except ValidationError as exc:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Invalid input: {exc.errors()}")],
            isError=True,
        )
    #here we mimic the dux peri simu
    simulation = compute_simulation(user)
    overall_gain = simulation["overall_gain"]
    logger.info("overall gain computed : gain=%s" , overall_gain)
    #we are going to hash the user data to display one link "per session"
    link_display = _hashbrown_user(user,link_bp,link_ce)
    #we populate the html
    html_out = _render_html(user, overall_gain, CONDITIONS_TEXT, link_display)
    data = _template_data(user, overall_gain, CONDITIONS_TEXT, link_display)
    logger.info("data=%s" , data)
    logger.info("Rendered HTML length=%s", len(html_out))
    if "{age}" in html_out or "{versement_initial}" in html_out:
        logger.warning("Template placeholders still present in rendered HTML")
    logger.debug("Structured content keys: %s", list(data.keys()))
    #we then return the output data and the html popupalated
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=f"La simulation est terminée. Si vous souhaitez \
                                   souscrire à notre PERI nous vous invitons à vous rendre sur le lien : {link_display}")],
        structuredContent=data,
        _meta={
            "openai/outputTemplate": WIDGET_TEMPLATE_URI,
            "openai/output": {
                "mimeType": MIME_TYPE,
                "text": html_out,
            },
        },
    )


app = mcp.streamable_http_app()

try:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    #we add a middleware to log the requests
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
    #if we do not use browser calls which might be the case we should delete these
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )
except Exception:
    pass


# if __name__ == "__main__":
#     import uvicorn

#     uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
