"""End-to-end pipeline: ingest → store → query agent."""

from datetime import datetime, timezone
from .ingestion import ingest_news
from .vector_store import upsert_articles
from agents.research_agent import ResearchAgent
from db.watchlist_data import get_tickers


def run_pipeline(
    tickers: list[str] | None = None,
    question: str | None = None,
    since: datetime | None = None,
):
    if tickers is None:
        tickers = get_tickers()
    print("=" * 60)
    print("Step 1: Ingesting news from Yahoo Finance...")
    articles = ingest_news(tickers, since=since)
    print(f"  → Fetched {len(articles)} articles\n")

    print("Step 2: Embedding and storing in ChromaDB...")
    n_chunks = upsert_articles(articles)
    print(f"  → Stored {n_chunks} chunks\n")

    q = question or f"Analyze {', '.join(tickers[:3])} and give me your best trade recommendation."
    print(f"Step 3: Running agent...\nQuestion: {q}\n")
    print("=" * 60)
    answer = ResearchAgent().analyze(q)
    print(answer)


if __name__ == "__main__":
    import sys
    from datetime import timedelta

    args = sys.argv[1:]

    # Optional --since YYYY-MM-DD flag
    since = None
    if "--since" in args:
        idx = args.index("--since")
        date_str = args.pop(idx + 1)
        args.pop(idx)
        since = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    q = " ".join(args) if args else None
    run_pipeline(question=q, since=since)
