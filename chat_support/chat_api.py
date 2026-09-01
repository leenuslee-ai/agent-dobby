"""REST API layer for the AI trading pipeline.

Endpoints
---------
POST   /login              — authenticate and receive a threadId
POST   /whatnext           — send a message to the ChatAgent

Run with:
    uvicorn chat_support.chat_api:app --reload --port 8800
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

from .chat_agent import ChatAgent

app = FastAPI(title="AI Trading Pipeline API")
_agent = ChatAgent()

# ── In-memory session store (threadId → username) ─────────────────────────────
_sessions: dict[str, str] = {}

# ── Hardcoded credentials (replace with DB lookup later) ─────────────────────
_VALID_USERS = {"lee": "lee"}


# ── Auth helper ───────────────────────────────────────────────────────────────

def _require_session(thread_id: str):
    if thread_id not in _sessions:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired threadId. Please login first.",
        )


# ── Request / Response models ─────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    threadId: str

class WhatNextRequest(BaseModel):
    threadId: str
    message: str

class WhatNextResponse(BaseModel):
    threadId: str
    response: dict
    trace: Optional[list] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/login", response_model=LoginResponse)
def login(req: LoginRequest) -> LoginResponse:
    if _VALID_USERS.get(req.username) != req.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    thread_id = str(uuid.uuid4())
    _sessions[thread_id] = req.username
    return LoginResponse(threadId=thread_id)


@app.post("/whatnext", response_model=WhatNextResponse)
def whatnext(req: WhatNextRequest) -> WhatNextResponse:
    _require_session(req.threadId)
    result = _agent.invoke(thread_id=req.threadId, message=req.message)
    response = result if isinstance(result, dict) else {"message": result}
    trace = response.pop("trace", None)
    print("whatnext Response")
    print(response)
    return WhatNextResponse(threadId=req.threadId, response=response, trace=trace)
