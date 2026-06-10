"""LLM API Proxy — deploys on EC2 alongside LayoutLM.

Forwards requests from your laptop (which has Zscaler blocking HTTPS to
api.groq.com / openrouter.ai) through this HTTP proxy on EC2 (no Zscaler).

Routes:
    POST /groq/v1/chat/completions      → https://api.groq.com/openai/v1/chat/completions
    POST /openrouter/v1/chat/completions → https://openrouter.ai/api/v1/chat/completions
    GET  /health                         → {"status": "ok", "proxy": true}

Deploy on EC2:
    pip install fastapi uvicorn httpx
    python llm_proxy.py   # runs on port 8080

From your laptop, set:
    GROQ_BASE_URL=http://13.201.122.188:8080/groq/v1
    OPENAI_BASE_URL=http://13.201.122.188:8080/openrouter/v1
"""
import os
import logging
import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("llm_proxy")

app = FastAPI(title="LLM Proxy", docs_url=None)

# Upstream targets
GROQ_UPSTREAM = "https://api.groq.com/openai/v1"
OPENROUTER_UPSTREAM = "https://openrouter.ai/api/v1"

# Shared HTTP client with connection pooling
_client = httpx.AsyncClient(timeout=180.0, follow_redirects=True)


@app.get("/health")
async def health():
    return {"status": "ok", "proxy": True, "routes": ["/groq/v1/...", "/openrouter/v1/..."]}


@app.api_route("/groq/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_groq(request: Request, path: str):
    """Forward to Groq API."""
    return await _forward(request, f"{GROQ_UPSTREAM}/{path}")


@app.api_route("/openrouter/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_openrouter(request: Request, path: str):
    """Forward to OpenRouter API."""
    return await _forward(request, f"{OPENROUTER_UPSTREAM}/{path}")


async def _forward(request: Request, upstream_url: str) -> Response:
    """Forward a request to upstream, passing through headers and body."""
    # Forward relevant headers (especially Authorization)
    headers = {}
    for key, value in request.headers.items():
        if key.lower() in ("authorization", "content-type", "accept", "user-agent",
                           "x-title", "http-referer"):
            headers[key] = value

    body = await request.body()
    method = request.method.upper()

    logger.info("[proxy] %s %s → %s (%d bytes)", method, request.url.path, upstream_url, len(body))

    try:
        resp = await _client.request(
            method=method,
            url=upstream_url,
            headers=headers,
            content=body,
        )
        # Stream response back
        response_headers = dict(resp.headers)
        # Remove hop-by-hop headers
        for h in ("transfer-encoding", "connection", "keep-alive"):
            response_headers.pop(h, None)

        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=response_headers,
        )
    except httpx.TimeoutException:
        logger.error("[proxy] Timeout: %s", upstream_url)
        return JSONResponse({"error": "upstream_timeout", "url": upstream_url}, status_code=504)
    except Exception as exc:
        logger.error("[proxy] Error: %s — %s", upstream_url, exc)
        return JSONResponse({"error": str(exc), "url": upstream_url}, status_code=502)


if __name__ == "__main__":
    port = int(os.getenv("PROXY_PORT", "8080"))
    logger.info("Starting LLM proxy on port %d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
