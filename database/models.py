"""数据库模型定义"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pathlib import Path

Base = declarative_base()


class Position(Base):
    """持仓记录表"""
    __tablename__ = 'positions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False)  # 股票代码
    name = Column(String(50))  # 股票名称
    cost = Column(Float, nullable=False)  # 成本价
    shares = Column(Integer, nullable=False)  # 持仓数量
    target_price = Column(Float)  # 目标价
    stop_loss = Column(Float)  # 止损价
    buy_date = Column(String(10))  # 买入日期
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<Position(code={self.code}, name={self.name}, cost={self.cost}, shares={self.shares})>"


class Candidate(Base):
    """候选池表"""
    __tablename__ = 'candidates'

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False)
    name = Column(String(50))
    select_date = Column(String(10))  # 选入日期
    buy_range_low = Column(Float)  # 买入区间下限
    buy_range_high = Column(Float)  # 买入区间上限
    target_price = Column(Float)  # 目标卖出价
    stop_loss = Column(Float)  # 止损价
    position_advice = Column(Text)  # 仓位建议
    reason = Column(Text)  # 选入理由
    score = Column(Float)  # 综合评分
    status = Column(String(20), default='pending')  # pending/bought/skipped/expired
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<Candidate(code={self.code}, name={self.name}, status={self.status})>"


class Signal(Base):
    """交易信号记录表"""
    __tablename__ = 'signals'

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False)
    name = Column(String(50))
    signal_type = Column(String(20), nullable=False)  # buy/sell/stop_loss/target/alert
    price = Column(Float)  # 触发价格
    triggered_at = Column(DateTime, default=datetime.now)
    action_taken = Column(Text)  # 用户操作记录
    notes = Column(Text)  # 备注

    def __repr__(self):
        return f"<Signal(code={self.code}, type={self.signal_type}, price={self.price})>"


class ReviewRecord(Base):
    """复盘记录表"""
    __tablename__ = 'review_records'

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False)
    name = Column(String(50))
    candidate_id = Column(Integer)  # 关联候选记录
    select_date = Column(String(10))  # 选股日期
    select_price = Column(Float)  # 选股时价格
    actual_return = Column(Float)  # 实际收益率
    hit_target = Column(Integer, default=0)  # 是否达标 1/0
    review_date = Column(String(10))  # 复盘日期
    notes = Column(Text)  # 复盘笔记
    created_at = Column(DateTime, default=datetime.now)

    def __repr__(self):
        return f"<ReviewRecord(code={self.code}, return={self.actual_return})>"


class StockCache(Base):
    """股票数据缓存表"""
    __tablename__ = 'stock_cache'

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, unique=True)
    name = Column(String(50))
    last_price = Column(Float)  # 最新价格
    change_pct = Column(Float)  # 涨跌幅
    volume = Column(Float)  # 成交量
    turnover = Column(Float)  # 成交额
    pe = Column(Float)  # 市盈率
    pb = Column(Float)  # 市净率
    total_mv = Column(Float)  # 总市值
    circ_mv = Column(Float)  # 流通市值
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


def get_database_path() -> Path:
    """获取数据库文件路径"""
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir / "stock.db"


def init_database():
    """初始化数据库"""
    db_path = get_database_path()
    engine = create_engine(f'sqlite:///{db_path}')
    Base.metadata.create_all(engine)
    return engine


def get_session():
    """获取数据库会话"""
    engine = init_database()
    Session = sessionmaker(bind=engine)
    return Session()