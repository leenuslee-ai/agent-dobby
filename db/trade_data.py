"""Trade persistence: save_trade() creates PortfolioTransaction entries and
automatically manages PortfolioHolding / CloseTradeReference records."""

import uuid
from datetime import datetime, timezone

from db.session import get_session
from db.models import PortfolioHolding, PortfolioTransaction, CloseTradeReference


def save_trade(
    account_id: str,
    ticker: str,
    side: str,
    open_close: str,
    qty: float,
    price: float,
    status: str = "filled",
    filled_at: datetime | None = None,
    broker_order_id: str | None = None,
) -> dict:
    """Persist a trade and maintain open holdings.

    Args:
        account_id:       PortfolioAccount.id
        ticker:           Stock symbol (e.g. "NVDA")
        side:             "BUY" or "SELL"
        open_close:       "Open" — opens a new holding row
                          "Close" — matches against open holdings (FIFO)
        qty:              Number of shares
        price:            Fill price per share
        status:           Transaction status (default "filled")
        filled_at:        Fill timestamp (defaults to now)
        broker_order_id:  Optional broker reference

    Returns:
        dict with the created transaction id and, for Close trades, the list
        of CloseTradeReference ids that were created.
    """
    if open_close not in ("Open", "Close"):
        raise ValueError(f"open_close must be 'Open' or 'Close', got '{open_close}'")
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be 'BUY' or 'SELL', got '{side}'")

    filled_at = filled_at or datetime.now(timezone.utc)

    with get_session() as session:
        # ── Create the transaction record ──────────────────────────────────────
        txn = PortfolioTransaction(
            id=str(uuid.uuid4()),
            account_id=account_id,
            broker_order_id=broker_order_id,
            ticker=ticker.upper(),
            side=side,
            open_close=open_close,
            qty=qty,
            price=price,
            status=status,
            filled_at=filled_at,
        )
        session.add(txn)
        session.flush()  # get txn.id before we reference it

        close_ref_ids = []

        if open_close == "Open":
            # ── Open: create a new holding row ─────────────────────────────────
            holding = PortfolioHolding(
                id=str(uuid.uuid4()),
                account_id=account_id,
                ticker=ticker.upper(),
                opening_transaction_date=filled_at,
                open_qty=qty,
                opening_transaction_type=side,
                open_price=price,
                pending_qty=qty,
                current_price=price,
                current_open_value=round(qty * price, 6),
                closed_value=0.0,
            )
            session.add(holding)

        else:
            # ── Close: match FIFO against open holdings with pending_qty > 0 ──
            open_holdings = (
                session.query(PortfolioHolding)
                .filter(
                    PortfolioHolding.account_id == account_id,
                    PortfolioHolding.ticker == ticker.upper(),
                    PortfolioHolding.pending_qty > 0,
                )
                .order_by(PortfolioHolding.opening_transaction_date)
                .all()
            )

            remaining = qty
            for holding in open_holdings:
                if remaining <= 0:
                    break

                allocated = min(holding.pending_qty, remaining)
                close_value = round(allocated * price, 6)

                ref = CloseTradeReference(
                    id=str(uuid.uuid4()),
                    holding_id=holding.id,
                    closing_transaction_id=txn.id,
                    closing_qty=allocated,
                    closing_price=price,
                    closing_date=filled_at,
                )
                session.add(ref)
                close_ref_ids.append(ref.id)

                holding.pending_qty = round(holding.pending_qty - allocated, 10)
                holding.closed_value = round(holding.closed_value + close_value, 6)
                holding.current_open_value = round(holding.pending_qty * holding.current_price, 6)

                remaining = round(remaining - allocated, 10)

        result = {
            "transaction_id": txn.id,
            "open_close":     open_close,
            "ticker":         ticker.upper(),
            "side":           side,
            "qty":            qty,
            "price":          price,
        }
        if close_ref_ids:
            result["close_ref_ids"] = close_ref_ids

    return result
