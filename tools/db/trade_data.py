"""Trade persistence: save_trade() creates PortfolioTransaction entries and
automatically manages PortfolioHolding / CloseTradeReference records."""

import uuid
from datetime import datetime, timezone

from tools.db.session import get_session
from tools.db.models import PortfolioAccount, PortfolioHolding, PortfolioTransaction, CloseTradeReference


# ── Serialisers ───────────────────────────────────────────────────────────────

def _holding_to_dict(h: PortfolioHolding) -> dict:
    return {
        "id":                       h.id,
        "account_id":               h.account_id,
        "ticker":                   h.ticker,
        "setup_name":               h.setup_name,
        "opening_transaction_date": h.opening_transaction_date.isoformat() if h.opening_transaction_date else None,
        "open_qty":                 h.open_qty,
        "opening_transaction_type": h.opening_transaction_type,
        "open_price":               h.open_price,
        "pending_qty":              h.pending_qty,
        "current_price":            h.current_price,
        "current_open_value":       h.current_open_value,
        "closed_value":             h.closed_value,
    }


def _transaction_to_dict(t: PortfolioTransaction) -> dict:
    return {
        "id":               t.id,
        "account_id":       t.account_id,
        "ticker":           t.ticker,
        "setup_name":       t.setup_name,
        "side":             t.side,
        "open_close":       t.open_close,
        "qty":              t.qty,
        "price":            t.price,
        "status":           t.status,
        "filled_at":        t.filled_at.isoformat() if t.filled_at else None,
        "broker_order_id":  t.broker_order_id,
    }


# ── Save helpers (operate inside an open session) ─────────────────────────────

def _create_transaction(session, account_id: str, ticker: str, side: str,
                         open_close: str, qty: float, price: float,
                         setup_name: str, status: str, filled_at: datetime,
                         broker_order_id: str | None) -> PortfolioTransaction:
    txn = PortfolioTransaction(
        id=str(uuid.uuid4()),
        account_id=account_id,
        broker_order_id=broker_order_id,
        ticker=ticker,
        setup_name=setup_name,
        side=side,
        open_close=open_close,
        qty=qty,
        price=price,
        status=status,
        filled_at=filled_at,
    )
    session.add(txn)
    session.flush()   # populate txn.id before it is referenced below
    return txn


def _open_holding(session, account_id: str, ticker: str, side: str,
                  setup_name: str, qty: float, price: float,
                  filled_at: datetime) -> PortfolioHolding:
    holding = PortfolioHolding(
        id=str(uuid.uuid4()),
        account_id=account_id,
        ticker=ticker,
        setup_name=setup_name,
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
    return holding


def _close_fifo(session, account_id: str, ticker: str, txn_id: str,
                qty: float, price: float, filled_at: datetime) -> list[str]:
    """Match qty against open holdings FIFO. Returns list of CloseTradeReference ids."""
    open_holdings = (
        session.query(PortfolioHolding)
        .filter(
            PortfolioHolding.account_id == account_id,
            PortfolioHolding.ticker == ticker,
            PortfolioHolding.pending_qty > 0,
        )
        .order_by(PortfolioHolding.opening_transaction_date)
        .all()
    )

    ref_ids   = []
    remaining = qty

    for holding in open_holdings:
        if remaining <= 0:
            break

        allocated   = min(holding.pending_qty, remaining)
        close_value = round(allocated * price, 6)

        ref = CloseTradeReference(
            id=str(uuid.uuid4()),
            holding_id=holding.id,
            closing_transaction_id=txn_id,
            closing_qty=allocated,
            closing_price=price,
            closing_date=filled_at,
        )
        session.add(ref)
        ref_ids.append(ref.id)

        holding.pending_qty        = round(holding.pending_qty - allocated, 10)
        holding.closed_value       = round(holding.closed_value + close_value, 6)
        holding.current_open_value = round(holding.pending_qty * holding.current_price, 6)
        remaining                  = round(remaining - allocated, 10)

    return ref_ids


# ── Public API ────────────────────────────────────────────────────────────────

def save_trade(
    account_id: str,
    ticker: str,
    side: str,
    open_close: str,
    qty: float,
    price: float,
    setup_name: str = "Manual",
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
        setup_name:       Name of the trading setup used (default "Manual")
        status:           Transaction status (default "filled")
        filled_at:        Fill timestamp (defaults to now)
        broker_order_id:  Optional broker reference

    Returns:
        dict with transaction_id and, for Close trades, close_ref_ids.
    """
    if open_close not in ("Open", "Close"):
        raise ValueError(f"open_close must be 'Open' or 'Close', got '{open_close}'")
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be 'BUY' or 'SELL', got '{side}'")

    ticker    = ticker.upper()
    filled_at = filled_at or datetime.now(timezone.utc)

    with get_session() as session:
        txn = _create_transaction(
            session, account_id, ticker, side, open_close,
            qty, price, setup_name, status, filled_at, broker_order_id,
        )

        close_ref_ids = []
        if open_close == "Open":
            _open_holding(session, account_id, ticker, side, setup_name, qty, price, filled_at)
        else:
            close_ref_ids = _close_fifo(session, account_id, ticker, txn.id, qty, price, filled_at)

        # Adjust account cash: BUY Open debits, SELL Close credits
        trade_value = round(qty * price, 6)
        account = session.query(PortfolioAccount).filter_by(id=account_id).first()
        if account is not None:
            if side == "BUY" and open_close == "Open":
                account.cash = round((account.cash or 0.0) - trade_value, 6)
            elif side == "SELL" and open_close == "Close":
                account.cash = round((account.cash or 0.0) + trade_value, 6)

        txn_id = txn.id  # capture before session closes

    result = {
        "transaction_id": txn_id,
        "open_close":     open_close,
        "ticker":         ticker,
        "side":           side,
        "qty":            qty,
        "price":          price,
    }
    if close_ref_ids:
        result["close_ref_ids"] = close_ref_ids
    return result


def get_open_holdings(
    account_id: str,
    opening_transaction_type: str = "BUY",
) -> list[dict]:
    """Return holdings with pending_qty > 0 for an account."""
    with get_session() as session:
        rows = (
            session.query(PortfolioHolding)
            .filter(
                PortfolioHolding.account_id == account_id,
                PortfolioHolding.pending_qty > 0,
                PortfolioHolding.opening_transaction_type == opening_transaction_type.upper(),
            )
            .order_by(PortfolioHolding.opening_transaction_date)
            .all()
        )
        return [_holding_to_dict(h) for h in rows]


def get_holdings(
    account_id: str,
    opening_transaction_type: str | None = None,
    opening_transaction_date: datetime | None = None,
) -> list[dict]:
    """Return holdings for an account with optional filters."""
    with get_session() as session:
        q = session.query(PortfolioHolding).filter(
            PortfolioHolding.account_id == account_id,
        )
        if opening_transaction_type is not None:
            q = q.filter(PortfolioHolding.opening_transaction_type == opening_transaction_type.upper())
        if opening_transaction_date is not None:
            q = q.filter(PortfolioHolding.opening_transaction_date >= opening_transaction_date)
        return [_holding_to_dict(h) for h in q.order_by(PortfolioHolding.opening_transaction_date).all()]


def get_trades(
    account_id: str,
    ticker: str | None = None,
    side: str | None = None,
    open_close: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> list[dict]:
    """Return transactions for an account with optional filters.

    Args:
        account_id:  PortfolioAccount.id
        ticker:      Filter by stock symbol (case-insensitive), or None for all
        side:        "BUY", "SELL", or None for all
        open_close:  "Open", "Close", or None for all
        from_date:   Include only trades with filled_at >= from_date
        to_date:     Include only trades with filled_at <= to_date

    Returns:
        List of transaction dicts ordered by filled_at ascending.
    """
    with get_session() as session:
        q = session.query(PortfolioTransaction).filter(
            PortfolioTransaction.account_id == account_id,
        )
        if ticker is not None:
            q = q.filter(PortfolioTransaction.ticker == ticker.upper())
        if side is not None:
            q = q.filter(PortfolioTransaction.side == side.upper())
        if open_close is not None:
            q = q.filter(PortfolioTransaction.open_close == open_close)
        if from_date is not None:
            q = q.filter(PortfolioTransaction.filled_at >= from_date)
        if to_date is not None:
            q = q.filter(PortfolioTransaction.filled_at <= to_date)
        return [_transaction_to_dict(t) for t in q.order_by(PortfolioTransaction.filled_at).all()]
