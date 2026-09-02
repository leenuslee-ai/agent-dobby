"""Fetch Yahoo Finance RSS news, summarize with Claude Haiku or local Llama."""

import hashlib
import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
from config import ANTHROPIC_API_KEY, SUMMARIZE_MODEL, MODEL_PROVIDER
from db.watchlist_data import get_tickers

_PROMPT_TEMPLATE = """\
This article was retrieved because it is relevant to stock {ticker}.

1. In 2-3 sentences, summarize ONLY what this article means for {ticker} specifically — \
its price, business, risk, or outlook. Ignore details unrelated to {ticker}.
2. Rate the sentiment of this news for {ticker} on a scale from -5 to +5 where:
   -5 = extremely negative, 0 = neutral, +5 = extremely positive.

Respond with valid JSON only, no extra text:
{{"summary": "<your summary>", "rating": <integer from -5 to 5>}}

Article:
{text}"""


def _parse_response(raw: str) -> tuple[str, int]:
    """Extract summary and rating from model JSON output."""
    try:
        # strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
        data = json.loads(cleaned)
        summary = str(data["summary"])
        rating = max(-5, min(5, int(data["rating"])))
        return summary, rating
    except Exception:
        # fallback: return raw text with neutral rating
        return raw.strip(), 0


def _summarize_anthropic(article: dict) -> tuple[str, int]:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    text = f"Title: {article['title']}\n\nContent: {article['summary']}"
    message = client.messages.create(
        model=SUMMARIZE_MODEL,
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": _PROMPT_TEMPLATE.format(ticker=article["ticker"], text=text),
        }],
    )
    return _parse_response(message.content[0].text)


def _summarize_ollama(article: dict) -> tuple[str, int]:
    import ollama
    text = f"Title: {article['title']}\n\nContent: {article['summary']}"
    response = ollama.chat(
        model=SUMMARIZE_MODEL,
        messages=[{
            "role": "user",
            "content": _PROMPT_TEMPLATE.format(ticker=article["ticker"], text=text),
        }],
    )
    return _parse_response(response["message"]["content"])


def summarize_article(article: dict) -> tuple[str, int]:
    """Return (condensed_summary, sentiment_rating) for the given article."""
    if MODEL_PROVIDER in ("ollama", "qwen"):
        return _summarize_ollama(article)
    return _summarize_anthropic(article)


# Map tickers to company name keywords for looser matching
_TICKER_ALIASES: dict[str, list[str]] = {
    "AAPL": ["apple"],
    "MSFT": ["microsoft"],
    "NVDA": ["nvidia"],
    "TSLA": ["tesla"],
    "AMZN": ["amazon"],
    "GOOGL": ["google", "alphabet"],
    "META": ["meta", "facebook"],
    "SPY": ["s&p", "s&p 500", "spdr"],
}


def _mentions_ticker(ticker: str, title: str, body: str) -> bool:
    """Return True if ticker symbol or a known company alias appears in the article text."""
    haystack = (title + " " + body).lower()
    if ticker.lower() in haystack:
        return True
    for alias in _TICKER_ALIASES.get(ticker, []):
        if alias in haystack:
            return True
    return False


def _parse_published(published_str: str) -> datetime | None:
    """Parse an RSS date string into a timezone-aware datetime, or None on failure."""
    try:
        return parsedate_to_datetime(published_str)
    except Exception:
        return None


def fetch_yahoo_rss(ticker: str, since: datetime | None = None) -> list[dict]:
    """Fetch up to 10 articles for ticker, optionally filtering to those published after `since`.

    `since` must be a timezone-aware datetime (e.g. datetime(2025, 1, 1, tzinfo=timezone.utc)).
    Yahoo Finance RSS has no server-side date filter, so this filters client-side.
    """
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    feed = feedparser.parse(url)
    articles = []
    for entry in feed.entries[:10]:
        published_str = entry.get("published", "")
        if since is not None:
            pub_dt = _parse_published(published_str)
            if pub_dt is None or pub_dt < since:
                continue
        raw = f"{ticker}:{entry.get('link', entry.get('title', ''))}"
        article_id = hashlib.md5(raw.encode()).hexdigest()
        articles.append({
            "id": article_id,
            "ticker": ticker,
            "title": entry.get("title", ""),
            "summary": entry.get("summary", ""),
            "link": entry.get("link", ""),
            "published": published_str,
        })
    return articles


def ingest_news(tickers: list[str] | None = None, since: datetime | None = None) -> list[dict]:
    if tickers is None:
        tickers = get_tickers()
    print(f"Using provider: {MODEL_PROVIDER} | summarize model: {SUMMARIZE_MODEL}")
    if since:
        print(f"Filtering articles published after: {since.strftime('%Y-%m-%d %H:%M %Z')}")
    results = []
    for ticker in tickers:
        print(f"Fetching news for {ticker}...")
        articles = fetch_yahoo_rss(ticker, since=since)
        if not articles:
            print(f"  (no articles after date filter)")
            continue
        for article in articles:
            if not _mentions_ticker(ticker, article["title"], article["summary"]):
                print(f"  ✗ skipped (no mention of {ticker}): {article['title'][:50]}...")
                continue
            summary, rating = summarize_article(article)
            article["condensed_summary"] = summary
            article["rating"] = rating
            results.append(article)
            print(f"  ✓ [{rating:+d}] {article['title'][:55]}...")
    return results


if __name__ == "__main__":
    # Example: only articles from the last 2 days
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=2)
    #articles = ingest_news(since=cutoff)
    articles = ingest_news(["NVDA"], since=cutoff)
    print(f"\nIngested {len(articles)} articles total.")
