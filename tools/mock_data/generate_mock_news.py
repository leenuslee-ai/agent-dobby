"""Generate and store simulated news articles for MOCK_STOCKS into ChromaDB.

Articles are pre-written with realistic financial language, spread across
a date range, and stored via the same upsert_articles() path used by the
live Yahoo Finance ingestion pipeline.

Company personas:
  DOBBY  — home-cleaning robotics startup (premium Roomba competitor)
  OWALA  — premium hydration / wellness drinkware brand
  MINI   — compact consumer electronics (smartwatches, earbuds, accessories)
  LUCAS  — streaming entertainment & content production platform
  PILLOW — sleep technology and comfort products company

Usage:
    python3 -m tools.mock_data.generate_mock_news
    python3 -m tools.mock_data.generate_mock_news --start 2026-08-28 --end 2026-10-31
    python3 -m tools.mock_data.generate_mock_news --clear   # wipe mock articles first
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

# ── Article templates ─────────────────────────────────────────────────────────
# Each entry: (title, condensed_summary, rating, day_offset_hint)
# day_offset_hint: rough number of days from start date to publish this article.
# Rating: -5 (very negative) to +5 (very positive).

_ARTICLES: dict[str, list[tuple[str, str, int, int]]] = {

    "DOBBY": [
        (
            "DOBBY Robotics Secures $40M Series B to Expand Home Cleaning Fleet",
            "DOBBY secured a $40M Series B funding round led by Sequoia, giving the company runway "
            "to scale its self-cleaning robot lineup. Analysts view this positively for DOBBY's growth "
            "trajectory and ability to compete with established players like iRobot.",
            4, 0,
        ),
        (
            "DOBBY Q2 Revenue Beats Estimates, Units Sold Up 22% YoY",
            "DOBBY reported Q2 revenue of $38M, beating consensus estimates of $34M. Unit sales grew "
            "22% year-over-year driven by its new DustBuster Pro model. Margins improved to 41%, "
            "signalling strong pricing power for DOBBY.",
            3, 7,
        ),
        (
            "Supply Chain Disruptions Hit DOBBY's Q3 Production Guidance",
            "DOBBY warned that semiconductor shortages may reduce Q3 unit output by up to 15%. "
            "The company is working with alternative suppliers but expects near-term pressure on DOBBY's "
            "gross margin. Shares may face headwinds until supply normalises.",
            -3, 14,
        ),
        (
            "DOBBY Launches Subscription Cleaning Service in 12 New Cities",
            "DOBBY announced the expansion of its robot-as-a-service subscription model to 12 additional "
            "US cities. Monthly recurring revenue from the service now accounts for 18% of DOBBY's total "
            "revenue, improving earnings predictability.",
            3, 21,
        ),
        (
            "DOBBY Partners with HomeDepot for In-Store Demo Rollout",
            "DOBBY signed a retail partnership with Home Depot to place demo units in 800 stores nationwide. "
            "The deal is expected to lower DOBBY's customer acquisition cost significantly and open a new "
            "mass-market distribution channel.",
            3, 28,
        ),
        (
            "Analyst Downgrades DOBBY Citing Valuation Concerns After Recent Run",
            "Morgan Stanley downgraded DOBBY from Overweight to Equal-Weight, citing a stretched valuation "
            "following the recent 30% rally. The analyst maintained a $115 price target but noted DOBBY "
            "needs to demonstrate consistent profitability before multiple expansion is justified.",
            -2, 35,
        ),
        (
            "DOBBY Files Patent for AI-Powered Mess Prediction Technology",
            "DOBBY filed a patent for predictive cleaning algorithms that anticipate high-traffic areas "
            "before they become dirty. If approved and commercialised, this technology could become a "
            "meaningful differentiator for DOBBY's premium product tier.",
            2, 42,
        ),
        (
            "DOBBY Reports Strong Back-to-School Season Demand",
            "DOBBY noted unusually strong retail demand in August driven by dorm and apartment purchases. "
            "Early sell-through data from retail partners suggests DOBBY is on track to beat Q3 unit "
            "guidance set at the start of the quarter.",
            3, 49,
        ),
        (
            "Competitor Launches Rival Product at 30% Lower Price Point Than DOBBY",
            "ShineBot unveiled a competing home-cleaning robot priced 30% below DOBBY's flagship model. "
            "While DOBBY's management expressed confidence in its premium positioning, investors are "
            "concerned about potential market share erosion in the mid-range segment.",
            -2, 56,
        ),
    ],

    "OWALA": [
        (
            "OWALA Bottles Sell Out Within Hours of Limited Edition Drop",
            "OWALA's new Stanley collaboration limited edition sold out across all SKUs within 4 hours. "
            "Secondary market prices hit 3× MSRP, signalling exceptional brand momentum and demand that "
            "outpaces current supply for OWALA's premium tier.",
            4, 0,
        ),
        (
            "OWALA Reports 45% Revenue Growth in H1, Raises Full-Year Guidance",
            "OWALA reported 45% year-over-year revenue growth in the first half, driven by social media "
            "virality and influencer partnerships. Management raised full-year revenue guidance to $210M, "
            "well above analyst expectations for OWALA.",
            5, 8,
        ),
        (
            "OWALA Expands into Fitness Nutrition Market with Protein Shaker Line",
            "OWALA announced a new line of fitness-focused shakers and supplement accessories, extending "
            "beyond its core drinkware business. The move targets the $15B sports nutrition market and "
            "is expected to add $20-25M in annual revenue for OWALA within two years.",
            3, 15,
        ),
        (
            "OWALA Faces Criticism Over Manufacturing Practices in Southeast Asia",
            "A Bloomberg investigation raised concerns about working conditions at OWALA's contract "
            "manufacturer in Vietnam. While OWALA management denies violations, reputational risk could "
            "weigh on the brand among its core millennial and Gen-Z consumer base.",
            -3, 22,
        ),
        (
            "OWALA Signs 3-Year Exclusive Deal with Major US Retailer",
            "OWALA signed an exclusive retail agreement with REI for a premium product line, securing "
            "prominent shelf space in 175 outdoor retail locations. Analysts expect this to drive "
            "significant incremental volume for OWALA in the outdoor and camping segment.",
            3, 29,
        ),
        (
            "OWALA Launches International Expansion Starting with Canada and UK",
            "OWALA announced international market entry into Canada and the UK, with localised colour "
            "palettes and sizing. International revenue could represent 15-20% of OWALA's total sales "
            "within 18 months if the launches gain similar traction to the US market.",
            3, 36,
        ),
        (
            "OWALA's TikTok Virality Drives 2M New App Downloads in September",
            "A series of viral TikTok videos featuring OWALA's FreeSip bottle drove over 2 million "
            "new app downloads in September alone. Social media sentiment for OWALA remains extremely "
            "positive, with the brand trending across multiple platforms.",
            4, 44,
        ),
        (
            "OWALA Gross Margins Contract as Raw Material Costs Rise",
            "OWALA's CFO warned that rising stainless steel and plastic resin costs could compress gross "
            "margins by 2-3 percentage points in Q4. While demand remains robust, OWALA may need to "
            "raise prices modestly or absorb the cost increase, pressuring near-term profitability.",
            -2, 52,
        ),
    ],

    "MINI": [
        (
            "MINI Smartwatch 3 Pro Receives Strong Early Reviews Ahead of Launch",
            "Pre-release reviews of MINI's Smartwatch 3 Pro praised its 10-day battery life and "
            "lightweight titanium case. Pre-orders surpassed MINI's internal targets by 40%, "
            "setting a positive tone for the flagship product cycle.",
            3, 0,
        ),
        (
            "MINI Reports Flat Q2 Revenue Amid Intense Competition",
            "MINI reported Q2 revenue of $62M, essentially flat versus last year, as competition from "
            "Apple Watch and Samsung Galaxy Watch intensified. MINI's management cited pricing pressure "
            "as a headwind but maintained full-year guidance.",
            -1, 9,
        ),
        (
            "MINI Earbuds Win Best-in-Class Award at Consumer Electronics Expo",
            "MINI's AirPod Ultra earbuds won the 'Best Audio Innovation' award at the Consumer "
            "Electronics Expo. The recognition is expected to boost MINI's brand awareness in the "
            "premium audio segment and drive holiday season demand.",
            2, 17,
        ),
        (
            "MINI Cuts 8% of Workforce in Restructuring to Focus on Core Products",
            "MINI announced a restructuring, eliminating 8% of its workforce and discontinuing two "
            "underperforming product lines. The company expects to save $12M annually but the move "
            "raised concerns about MINI's growth ambitions.",
            -2, 24,
        ),
        (
            "MINI Signs Enterprise Deal to Supply Smartwatches to Healthcare Networks",
            "MINI secured a $28M enterprise contract to supply health-monitoring smartwatches to three "
            "US hospital networks. The deal diversifies MINI's revenue beyond consumer retail and "
            "opens a higher-margin B2B channel.",
            3, 31,
        ),
        (
            "MINI Launches Recycled-Material Product Line, Targeting ESG Investors",
            "MINI unveiled a new product line made from 80% recycled materials, targeting ESG-focused "
            "consumers and institutional investors. While margins on the new line are slightly lower, "
            "MINI expects improved brand perception and access to ESG-screened funds.",
            2, 38,
        ),
        (
            "Analyst Maintains MINI at Hold — Needs Catalyst to Break Out",
            "Jefferies maintained its Hold rating on MINI with a $31 price target, noting the stock "
            "has been range-bound for six months. The analyst said MINI needs a clear product "
            "breakthrough or margin expansion story before the valuation becomes compelling.",
            0, 46,
        ),
        (
            "MINI Holiday Pre-Order Numbers Disappoint vs Internal Targets",
            "MINI disclosed that early holiday pre-order numbers came in 12% below internal targets. "
            "The company attributed the miss to shipping delays and inventory build timing. MINI "
            "assured investors it expects to fulfil all pre-orders before December 25.",
            -2, 55,
        ),
    ],

    "LUCAS": [
        (
            "LUCAS Streaming Loses 1.2M Subscribers in Q2 — Worst Quarter on Record",
            "LUCAS reported its worst subscriber quarter on record, losing 1.2M paid members as "
            "password-sharing crackdowns drove churn. Revenue fell 8% year-over-year and LUCAS "
            "management cut full-year subscriber guidance significantly.",
            -4, 0,
        ),
        (
            "LUCAS Content Budget Slashed 25% as Company Seeks Path to Profitability",
            "LUCAS announced a 25% reduction in its content budget, cancelling 14 original series "
            "in development. While the move will improve near-term cash flow, concerns persist about "
            "LUCAS's ability to retain subscribers with a thinner content slate.",
            -3, 8,
        ),
        (
            "LUCAS Launches Ad-Supported Tier — Early Uptake Below Expectations",
            "LUCAS's new ad-supported subscription tier, launched at $4.99/month, attracted 280,000 "
            "subscribers in its first month, below the company's guidance of 400,000. Advertising CPMs "
            "also came in lower than expected, limiting LUCAS's near-term revenue uplift.",
            -2, 16,
        ),
        (
            "LUCAS Hit Original Film Breaks Streaming Records But Can't Reverse Trend",
            "LUCAS's original film 'Velocity' set a new company streaming record with 45M views in its "
            "opening weekend. While positive for LUCAS's brand, analysts note one hit title is unlikely "
            "to reverse the structural subscriber decline the platform faces.",
            1, 24,
        ),
        (
            "LUCAS Explores Sale of Sports Rights Package to Reduce Debt Load",
            "Reuters reported LUCAS is in preliminary talks to sell its sports streaming rights bundle "
            "for $800M to reduce its $2.4B debt load. While the sale would improve LUCAS's balance "
            "sheet, it would remove a key content differentiator from the platform.",
            -1, 32,
        ),
        (
            "LUCAS CEO Replaced as Board Accelerates Turnaround Strategy",
            "LUCAS's board replaced its CEO with an interim executive from a cost-restructuring "
            "background. The move signals the board is prioritising margin improvement over growth "
            "for LUCAS, which investors interpreted as a negative for long-term content investment.",
            -3, 40,
        ),
        (
            "LUCAS Reports Narrower-Than-Expected Q3 Loss, Shares Bounce",
            "LUCAS reported a Q3 net loss of $42M, narrower than analyst estimates of $65M, driven "
            "by the content budget cuts. While not profitable, LUCAS's trajectory toward breakeven "
            "improved and the stock bounced 8% on the day.",
            2, 48,
        ),
        (
            "LUCAS Subscriber Churn Stabilises in October — First Positive Signal in 18 Months",
            "LUCAS disclosed that October subscriber churn fell to its lowest rate in 18 months. "
            "Management credited the new ad-supported tier and improved content discovery features. "
            "Analysts remain cautious but acknowledge LUCAS may be approaching a turning point.",
            2, 56,
        ),
    ],

    "PILLOW": [
        (
            "PILLOW Smart Mattress Earns Top Rating from Sleep Foundation",
            "PILLOW's flagship AI-adjusting smart mattress received the Sleep Foundation's highest "
            "rating, boosting brand credibility significantly. The endorsement is expected to drive "
            "conversion rates on PILLOW's direct-to-consumer website and improve word-of-mouth referrals.",
            3, 0,
        ),
        (
            "PILLOW Q2 Results Beat: Revenue Up 18%, DTC Margin Reaches 52%",
            "PILLOW reported Q2 revenue of $48M, up 18% year-over-year, with direct-to-consumer "
            "margins improving to 52%. Management noted that PILLOW's subscription sleep-tracking "
            "service now contributes 22% of total revenue, adding predictability to earnings.",
            4, 9,
        ),
        (
            "PILLOW Raises Prices Across Premium Lineup by 8-12%",
            "PILLOW announced a price increase of 8-12% across its premium mattress and pillow line, "
            "citing raw material cost pressures. Analysts are split on whether PILLOW's brand loyalty "
            "is strong enough to absorb the increase without volume decline.",
            -1, 17,
        ),
        (
            "PILLOW Partners with Major Hotel Chain for 50,000 Room Rollout",
            "PILLOW signed a B2B contract with a major US hotel chain to supply smart pillows and "
            "sleep trackers for 50,000 rooms across 200 properties. The deal represents PILLOW's "
            "largest single contract and validates enterprise demand for the product.",
            4, 25,
        ),
        (
            "PILLOW Faces Class Action Lawsuit Over Sleep Data Privacy",
            "A class-action lawsuit was filed against PILLOW alleging its sleep-tracking app collects "
            "biometric data without sufficient user consent. While PILLOW denies wrongdoing, legal "
            "costs and potential regulatory scrutiny could weigh on the company's growth.",
            -3, 33,
        ),
        (
            "PILLOW Launches Children's Sleep Line — Targets $5B Market Segment",
            "PILLOW unveiled a children's sleep health product line including weighted blankets, "
            "sleep-training night lights, and a kids app. Management sees this as a $5B addressable "
            "market extension that leverages PILLOW's existing brand and technology platform.",
            3, 40,
        ),
        (
            "PILLOW Named to Fast Company's Most Innovative Companies List",
            "PILLOW was named to Fast Company's annual Most Innovative Companies list, recognised "
            "for its AI-powered sleep optimisation technology. The accolade is expected to boost "
            "PILLOW's brand awareness and attract top engineering talent.",
            2, 48,
        ),
        (
            "PILLOW Q3 Revenue Guidance Slightly Below Street Estimates",
            "PILLOW's Q3 revenue guidance of $51-53M came in slightly below analyst consensus of $55M. "
            "Management attributed the conservative guidance to the hotel deal phasing and the legal "
            "overhang from the privacy lawsuit. PILLOW remains confident in its full-year outlook.",
            -1, 56,
        ),
    ],
}


# ── Date helpers ──────────────────────────────────────────────────────────────

def _spread_dates(
    start: datetime, end: datetime, n: int, rng_seed: int
) -> list[datetime]:
    """Return n business-day dates spread roughly evenly across [start, end]."""
    import random
    rng   = random.Random(rng_seed)
    span  = (end - start).days
    step  = span / max(n - 1, 1)
    dates = []
    for i in range(n):
        base   = start + timedelta(days=i * step)
        jitter = timedelta(days=rng.uniform(-1.5, 1.5))
        dt     = base + jitter
        # Skip weekends
        while dt.weekday() >= 5:
            dt += timedelta(days=1)
        dt = dt.replace(hour=rng.choice([8, 9, 10, 13, 14]), minute=rng.randint(0, 59),
                        second=0, microsecond=0, tzinfo=timezone.utc)
        dates.append(dt)
    return dates


def _make_article(ticker: str, title: str, summary: str, rating: int,
                  pub_dt: datetime) -> dict:
    published = format_datetime(pub_dt, usegmt=True)
    raw       = f"{ticker}:{title}:{pub_dt.date()}"
    article_id = hashlib.md5(raw.encode()).hexdigest()
    return {
        "id":                article_id,
        "ticker":            ticker,
        "title":             title,
        "summary":           summary,        # raw body (not embedded)
        "condensed_summary": summary,        # embedded text
        "link":              f"https://mock-news.example.com/{ticker.lower()}/{article_id[:8]}",
        "published":         published,
        "rating":            rating,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def generate(start_date: str = "2026-08-28", end_date: str = "2026-10-31",
             clear_existing: bool = False) -> int:
    from tools.rag_yahoo.vector_store import upsert_articles, get_collection

    start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end   = datetime.strptime(end_date,   "%Y-%m-%d").replace(tzinfo=timezone.utc)

    if clear_existing:
        print("[mock_news] Clearing existing mock articles from ChromaDB...")
        col = get_collection()
        for ticker in _ARTICLES:
            try:
                existing = col.get(where={"ticker": ticker})
                if existing["ids"]:
                    col.delete(ids=existing["ids"])
                    print(f"  Deleted {len(existing['ids'])} chunks for {ticker}")
            except Exception as e:
                print(f"  Could not clear {ticker}: {e}")

    all_articles = []
    for ticker, templates in _ARTICLES.items():
        seed  = sum(ord(c) for c in ticker)
        dates = _spread_dates(start, end, len(templates), rng_seed=seed)
        for (title, summary, rating, _hint), pub_dt in zip(templates, dates):
            all_articles.append(_make_article(ticker, title, summary, rating, pub_dt))

    print(f"[mock_news] Storing {len(all_articles)} articles "
          f"({start_date} → {end_date}) into ChromaDB...")
    n_chunks = upsert_articles(all_articles)
    print(f"[mock_news] Done — {n_chunks} chunks stored.")
    return n_chunks


def main():
    parser = argparse.ArgumentParser(description="Generate mock news for MOCK_STOCKS")
    parser.add_argument("--start",  default="2026-08-28", help="Start date YYYY-MM-DD")
    parser.add_argument("--end",    default="2026-10-31", help="End date YYYY-MM-DD")
    parser.add_argument("--clear",  action="store_true",  help="Delete existing mock articles first")
    args = parser.parse_args()
    generate(start_date=args.start, end_date=args.end, clear_existing=args.clear)


if __name__ == "__main__":
    main()
