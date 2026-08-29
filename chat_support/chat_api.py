"""REST API layer for the AI trading pipeline.

Endpoints
---------
POST   /login              — authenticate and receive a threadId
POST   /whatnext           — send a message to the ChatAgent

GET    /setups             — list all saved trading setups
GET    /setups/{name_or_id}— get a single setup with its full definition
POST   /setups             — create or update a setup
DELETE /setups/{name_or_id}— delete a setup

Run with:
    uvicorn chat_support.chat_api:app --reload --port 8800
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from backtest import SetupStore
from .chat_agent import ChatAgent

app = FastAPI(title="AI Trading Pipeline API")
_agent = ChatAgent()
_store = SetupStore()

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

class SetupRequest(BaseModel):
    threadId:    str
    name:        str
    description: str = ""
    definition:  dict

class SetupResponse(BaseModel):
    id:          str
    name:        str
    description: str
    definition:  dict
    created_at:  str

class SetupSummary(BaseModel):
    id:          str
    name:        str
    description: str
    created_at:  str


# ── Auth endpoints ────────────────────────────────────────────────────────────

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
    return WhatNextResponse(threadId=req.threadId, response=response)


# ── Setup CRUD endpoints ──────────────────────────────────────────────────────

@app.get("/setups", response_model=list[SetupSummary])
def list_setups(threadId: str) -> list[SetupSummary]:
    _require_session(threadId)
    return [SetupSummary(**s) for s in _store.list()]


@app.get("/setups/{name_or_id}", response_model=SetupResponse)
def get_setup(name_or_id: str, threadId: str) -> SetupResponse:
    _require_session(threadId)
    record = _store.get(name_or_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Setup '{name_or_id}' not found.")
    return SetupResponse(**record)


@app.post("/setups", response_model=dict, status_code=status.HTTP_201_CREATED)
def save_setup(req: SetupRequest) -> dict:
    _require_session(req.threadId)
    setup_id = _store.save(
        name=req.name,
        description=req.description,
        definition=req.definition,
    )
    return {"id": setup_id, "name": req.name}


@app.delete("/setups/{name_or_id}", response_model=dict)
def delete_setup(name_or_id: str, threadId: str) -> dict:
    _require_session(threadId)
    deleted = _store.delete(name_or_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Setup '{name_or_id}' not found.")
    return {"deleted": name_or_id}
