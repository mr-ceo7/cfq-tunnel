"""
A Vercel proxy can't carry WebSockets, so browsers must open them on the tunnel's own address.
The backend can read that address from cloudflared's metrics endpoint and hand it to the browser,
e.g. alongside a short-lived ticket, so the frontend never needs rebuilding when the tunnel moves.

    pip install fastapi httpx
"""

import time

import httpx
from fastapi import FastAPI

METRICS = "http://127.0.0.1:20242"  # the --metrics address cfq-tunnel was started with
app = FastAPI()
_cache = {"url": "", "at": 0.0}


async def tunnel_url() -> str:
    if time.monotonic() - _cache["at"] > 10:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                host = (await client.get(f"{METRICS}/quicktunnel")).json().get("hostname")
            _cache.update(url=f"https://{host}" if host else "", at=time.monotonic())
        except (httpx.HTTPError, ValueError):
            pass
    return _cache["url"]


@app.get("/api/ws-address")
async def ws_address():
    base = await tunnel_url()
    return {"ws_url": base.replace("https://", "wss://", 1) if base else ""}
