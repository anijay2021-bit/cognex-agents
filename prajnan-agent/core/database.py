from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from config.settings import settings

Base = declarative_base()
# ADDED: timeout to prevent hanging on locks
engine = create_engine(settings.database_url, echo=False, connect_args={'timeout': 20})
SessionLocal = sessionmaker(bind=engine)

class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(50), unique=True, nullable=True)
    symbol = Column(String(50), nullable=False)
    instrument_type = Column(String(10))
    underlying = Column(String(20))
    strike = Column(Float, nullable=True)
    expiry = Column(String(20), nullable=True)
    direction = Column(String(4))
    quantity = Column(Integer, nullable=False)
    entry_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    entry_time = Column(DateTime, default=datetime.utcnow)
    exit_time = Column(DateTime, nullable=True)
    pnl_rs = Column(Float, default=0.0)
    status = Column(String(20), default="PENDING")
    strategy_used = Column(String(50), nullable=True)
    reason = Column(Text, nullable=True)
    mode = Column(String(10), default="PAPER")

def init_db():
    Base.metadata.create_all(bind=engine)
    print("Database initialised successfully")
