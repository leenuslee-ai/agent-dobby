from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Text, Float, Integer, BigInteger,
    Boolean, DateTime, ForeignKey, JSON, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def _now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Config(Base):
    __tablename__ = "configs"

    key   = Column(String(255), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

# Not used for now
class TradeSetup(Base):
    __tablename__ = "trade_setups"

    id          = Column(String(36), primary_key=True)
    name        = Column(String(255), nullable=False)
    ticker      = Column(String(20), nullable=False)
    direction   = Column(String(10), nullable=False)   # BUY | SELL
    conditions  = Column(JSON, nullable=False)          # list of condition dicts
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime(timezone=True), default=_now)
    updated_at  = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    backtest_runs = relationship("BacktestRun", back_populates="setup")


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id           = Column(String(36), primary_key=True)
    setup_id     = Column(String(36), ForeignKey("trade_setups.id"), nullable=False)
    ticker       = Column(String(20), nullable=False)
    start_date   = Column(DateTime(timezone=True), nullable=False)
    end_date     = Column(DateTime(timezone=True), nullable=False)
    initial_cash = Column(Float, nullable=False)
    final_value  = Column(Float)
    total_return = Column(Float)
    sharpe_ratio = Column(Float)
    max_drawdown = Column(Float)
    total_trades = Column(Integer)
    extra_stats  = Column(JSON)
    created_at   = Column(DateTime(timezone=True), default=_now)

    setup        = relationship("TradeSetup", back_populates="backtest_runs")
    transactions = relationship("BacktestTransaction", back_populates="run")


class BacktestTransaction(Base):
    __tablename__ = "backtest_transactions"

    id            = Column(String(36), primary_key=True)
    run_id        = Column(String(36), ForeignKey("backtest_runs.id"), nullable=False)
    ticker        = Column(String(20), nullable=False)
    side          = Column(String(10), nullable=False)   # BUY | SELL
    qty           = Column(Float, nullable=False)
    price         = Column(Float, nullable=False)
    commission    = Column(Float, default=0.0)
    pnl           = Column(Float)
    timestamp     = Column(DateTime(timezone=True), nullable=False)

    run = relationship("BacktestRun", back_populates="transactions")


class PortfolioAccount(Base):
    __tablename__ = "portfolio_accounts"

    id           = Column(String(36), primary_key=True)
    broker       = Column(String(50), nullable=False)   # e.g. "alpaca"
    account_id   = Column(String(100), nullable=False)
    display_name = Column(String(255))
    is_paper     = Column(Boolean, default=True)
    cash         = Column(Float)
    equity       = Column(Float)
    synced_at    = Column(DateTime(timezone=True))
    created_at   = Column(DateTime(timezone=True), default=_now)

    __table_args__ = (UniqueConstraint("broker", "account_id"),)

    holdings     = relationship("PortfolioHolding", back_populates="account")
    transactions = relationship("PortfolioTransaction", back_populates="account")


class PortfolioHolding(Base):
    __tablename__ = "portfolio_holdings"

    id         = Column(String(36), primary_key=True)
    account_id = Column(String(36), ForeignKey("portfolio_accounts.id"), nullable=False)
    ticker     = Column(String(20), nullable=False)
    qty        = Column(Float, nullable=False)
    avg_cost   = Column(Float)
    market_value = Column(Float)
    unrealized_pnl = Column(Float)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (UniqueConstraint("account_id", "ticker"),)

    account = relationship("PortfolioAccount", back_populates="holdings")


class PortfolioTransaction(Base):
    __tablename__ = "portfolio_transactions"

    id           = Column(String(36), primary_key=True)
    account_id   = Column(String(36), ForeignKey("portfolio_accounts.id"), nullable=False)
    broker_order_id = Column(String(100))
    ticker       = Column(String(20), nullable=False)
    side         = Column(String(10), nullable=False)   # BUY | SELL
    qty          = Column(Float, nullable=False)
    price        = Column(Float)
    status       = Column(String(20), nullable=False)   # filled | cancelled | pending
    filled_at    = Column(DateTime(timezone=True))
    created_at   = Column(DateTime(timezone=True), default=_now)

    account = relationship("PortfolioAccount", back_populates="transactions")


class Watchlist(Base):
    __tablename__ = "watchlist"

    ticker    = Column(String(20), primary_key=True)
    industry  = Column(String(100))
    category  = Column(String(100))
    setups    = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    added_at  = Column(DateTime(timezone=True), default=_now)


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id         = Column(BigInteger, primary_key=True, autoincrement=True)
    agent      = Column(String(100), nullable=False)   # e.g. "portfolio_manager"
    level      = Column(String(20), nullable=False)    # INFO | WARNING | ERROR
    message    = Column(Text, nullable=False)
    context    = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=_now)
