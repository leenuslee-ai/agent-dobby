import os
from dotenv import load_dotenv

load_dotenv()

# ── Provider switch ──────────────────────────────────────────────────────────
# Options: "anthropic" | "ollama" | "qwen"
# "ollama" → Llama 3.2 / 3.1   (ollama pull llama3.2 && ollama pull llama3.1)
# "qwen"   → Qwen3 4B           (ollama pull qwen3:4b)
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "anthropic").lower()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

def get_tickers(active_only: bool = True) -> list[str]:
    """Return tickers from the watchlist table."""
    from db.session import get_session
    from db.models import Watchlist
    with get_session() as session:
        q = session.query(Watchlist.ticker)
        if active_only:
            q = q.filter(Watchlist.is_active == True)
        return [row.ticker for row in q.order_by(Watchlist.ticker).all()]

# ChromaDB
CHROMA_DB_PATH = "./chroma_db"
COLLECTION_NAME = "finance_news"

# Embedding model (local, no API key needed)
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# RAG retrieval
TOP_K_RESULTS = 5

# ── Model names per provider ─────────────────────────────────────────────────
MODELS = {
    "anthropic": {
        "summarize": "claude-haiku-4-5-20251001",
        "agent":     "claude-sonnet-4-6",
    },
    "ollama": {
        "summarize": "llama3.2",   # ollama pull llama3.2
        "agent":     "qwen3.5:9b",   # ollama pull llama3.1
    },
    "qwen": {
        "summarize": "qwen3.5:9b",   # ollama pull qwen3:4b
        "agent":     "qwen3.5:9b",   # ollama pull qwen3:4b
    },
    "gemma": {
        "summarize": "gemma4:26b-a4b",   # ollama pull qwen3:4b
        "agent":     "gemma4:26b-a4b",   # ollama pull gemma3:7b or gemma4:26b-a4b
    }

}

SUMMARIZE_MODEL = MODELS[MODEL_PROVIDER]["summarize"]
AGENT_MODEL     = MODELS[MODEL_PROVIDER]["agent"]

# ── Chat agent tracing ───────────────────────────────────────────────────────
# Set CHAT_AGENT_TRACE=true in .env to include an execution trace in /whatnext
CHAT_AGENT_TRACE = os.getenv("CHAT_AGENT_TRACE", "false").lower() == "true"

# ── Alpha Vantage ────────────────────────────────────────────────────────────
ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "")

# MCP server transport: "streamable_http" (Alpha Vantage hosted) or "stdio" (local subprocess)
ALPHAVANTAGE_MCP_TRANSPORT = os.getenv("ALPHAVANTAGE_MCP_TRANSPORT", "streamable_http")
# For streamable_http: Alpha Vantage hosted MCP endpoint (apikey appended automatically)
ALPHAVANTAGE_MCP_SSE_URL   = os.getenv("ALPHAVANTAGE_MCP_SSE_URL", "https://mcp.alphavantage.co/mcp")
# For stdio transport: command to launch the MCP server process
ALPHAVANTAGE_MCP_COMMAND   = os.getenv("ALPHAVANTAGE_MCP_COMMAND", "uvx")
ALPHAVANTAGE_MCP_ARGS      = os.getenv("ALPHAVANTAGE_MCP_ARGS", "alphavantage-mcp")

# ── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://dobby:Dobby&Friends888*@localhost:5432/agent_dobby",
)

# ── Alpaca ───────────────────────────────────────────────────────────────────
ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
# Set ALPACA_PAPER=false in .env to trade live (use with caution)
ALPACA_PAPER = os.getenv("ALPACA_PAPER", "true").lower() != "false"
ALPACA_MCP_MODE = os.getenv("ALPACA_MCP_MODE", "true").lower() != "false"
