FROM python:3.12.12-slim

WORKDIR /app/custom_version

COPY custom_version/ /app/custom_version

RUN pip install --upgrade pip

RUN pip install --no-cache-dir fastmcp pandas plotly openai uvicorn pyyaml pydantic

EXPOSE 8000

CMD ["uvicorn","mcp_server:app","--host","0.0.0.0","--port","8000"]