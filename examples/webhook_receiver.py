"""
A minimal receiver for `cfq-tunnel run --webhook https://your-backend/tunnel-address`.
cfq-tunnel POSTs {"url": "https://<host>.trycloudflare.com", "hostname": "<host>.trycloudflare.com"}
with `Authorization: Bearer $CFQ_WEBHOOK_TOKEN` when that variable is set.

    pip install fastapi
"""

import hmac
import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

TOKEN = os.environ.get("CFQ_WEBHOOK_TOKEN", "")
app = FastAPI()
current = {"url": ""}


class Address(BaseModel):
    url: str
    hostname: str


@app.post("/tunnel-address")
async def update(address: Address, authorization: str = Header("")):
    if TOKEN and not hmac.compare_digest(authorization, f"Bearer {TOKEN}"):
        raise HTTPException(401)
    if not address.hostname.endswith(".trycloudflare.com"):
        raise HTTPException(422, "not a quick tunnel address")
    current["url"] = address.url
    return {"ok": True}


@app.get("/tunnel-address")
async def read():
    return current
