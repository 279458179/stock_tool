"""数据库操作模块"""
from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session
from .models import (
    Position, Candidate, Signal, ReviewRecord, StockCache,
    get_session, init_database
)


class PositionDB:
    """持仓数据库操作"""

    def __init__(self, session: Optional[Session] = None):
        self.session = session or get_session()

    def add_position(
        self,
        code: str,
        cost: float,
        shares: int,
        name: Optional[str] = None,
        target_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        buy_date: Optional[str] = None
    ) -> Position:
        """添加持仓"""
        position = Position(
            code=code,
            name=name,
            cost=cost,
            shares=shares,
            target_price=target_price,
            stop_loss=stop_loss,
            buy_date=buy_date or datetime.now().strftime("%Y-%m-%d")
        )
        self.session.add(position)
        self.session.commit()
        return position

    def remove_position(self, code: str) -> bool:
        """删除持仓"""
        position = self.session.query(Position).filter(
            Position.code == code
        ).first()
        if position:
            self.session.delete(position)
            self.session.commit()
            return True
        return False

    def get_position(self, code: str) -> Optional[Position]:
        """获取单个持仓"""
        return self.session.query(Position).filter(
            Position.code == code
        ).first()

    def get_all_positions(self) -> List[Position]:
        """获取所有持仓"""
        return self.session.query(Position).all()

    def update_position(
        self,
        code: str,
        **kwargs
    ) -> Optional[Position]:
        """更新持仓"""
        position = self.get_position(code)
        if position:
            for key, value in kwargs.items():
                if hasattr(position, key):
                    setattr(position, key, value)
            self.session.commit()
        return position

    def get_total_cost(self) -> float:
        """获取总成本"""
        positions = self.get_all_positions()
        return sum(p.cost * p.shares for p in positions)


class CandidateDB:
    """候选池数据库操作"""

    def __init__(self, session: Optional[Session] = None):
        self.session = session or get_session()

    def add_candidate(
        self,
        code: str,
        name: Optional[str] = None,
        select_date: Optional[str] = None,
        buy_range_low: Optional[float] = None,
        buy_range_high: Optional[float] = None,
        target_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        position_advice: Optional[str] = None,
        reason: Optional[str] = None,
        score: Optional[float] = None
    ) -> Candidate:
        """添加候选股"""
        candidate = Candidate(
            code=code,
            name=name,
            select_date=select_date or datetime.now().strftime("%Y-%m-%d"),
            buy_range_low=buy_range_low,
            buy_range_high=buy_range_high,
            target_price=target_price,
            stop_loss=stop_loss,
            position_advice=position_advice,
            reason=reason,
            score=score
        )
        self.session.add(candidate)
        self.session.commit()
        return candidate

    def get_candidate(self, code: str) -> Optional[Candidate]:
        """获取单个候选股"""
        return self.session.query(Candidate).filter(
            Candidate.code == code
        ).first()

    def get_pending_candidates(self) -> List[Candidate]:
        """获取待处理的候选股"""
        return self.session.query(Candidate).filter(
            Candidate.status == 'pending'
        ).all()

    def get_today_candidates(self) -> List[Candidate]:
        """获取今日候选股"""
        today = datetime.now().strftime("%Y-%m-%d")
        return self.session.query(Candidate).filter(
            Candidate.select_date == today,
            Candidate.status == 'pending'
        ).all()

    def get_all_candidates(self) -> List[Candidate]:
        """获取所有候选股"""
        return self.session.query(Candidate).all()

    def update_status(self, code: str, status: str) -> Optional[Candidate]:
        """更新候选股状态"""
        candidate = self.get_candidate(code)
        if candidate:
            candidate.status = status
            self.session.commit()
        return candidate

    def clear_expired_candidates(self, days: int = 3) -> int:
        """清理过期候选股"""
        expire_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        count = self.session.query(Candidate).filter(
            Candidate.select_date < expire_date,
            Candidate.status == 'pending'
        ).update({'status': 'expired'})
        self.session.commit()
        return count


class SignalDB:
    """信号数据库操作"""

    def __init__(self, session: Optional[Session] = None):
        self.session = session or get_session()

    def add_signal(
        self,
        code: str,
        signal_type: str,
        price: float,
        name: Optional[str] = None,
        action_taken: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Signal:
        """添加交易信号"""
        signal = Signal(
            code=code,
            name=name,
            signal_type=signal_type,
            price=price,
            action_taken=action_taken,
            notes=notes
        )
        self.session.add(signal)
        self.session.commit()
        return signal

    def get_today_signals(self) -> List[Signal]:
        """获取今日信号"""
        today = datetime.now().date()
        return self.session.query(Signal).filter(
            Signal.triggered_at >= today
        ).all()

    def get_signals_by_code(self, code: str) -> List[Signal]:
        """获取指定股票的信号"""
        return self.session.query(Signal).filter(
            Signal.code == code
        ).order_by(Signal.triggered_at.desc()).all()


class ReviewDB:
    """复盘数据库操作"""

    def __init__(self, session: Optional[Session] = None):
        self.session = session or get_session()

    def add_review(
        self,
        code: str,
        select_date: str,
        select_price: float,
        actual_return: float,
        name: Optional[str] = None,
        candidate_id: Optional[int] = None,
        hit_target: Optional[int] = None,
        notes: Optional[str] = None
    ) -> ReviewRecord:
        """添加复盘记录"""
        review = ReviewRecord(
            code=code,
            name=name,
            candidate_id=candidate_id,
            select_date=select_date,
            select_price=select_price,
            actual_return=actual_return,
            hit_target=hit_target or (1 if actual_return > 0 else 0),
            review_date=datetime.now().strftime("%Y-%m-%d"),
            notes=notes
        )
        self.session.add(review)
        self.session.commit()
        return review

    def get_reviews_by_days(self, days: int = 7) -> List[ReviewRecord]:
        """获取指定天数内的复盘记录"""
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return self.session.query(ReviewRecord).filter(
            ReviewRecord.review_date >= start_date
        ).all()

    def get_stats(self, days: int = 30) -> dict:
        """获取统计数据"""
        reviews = self.get_reviews_by_days(days)
        if not reviews:
            return {'total': 0, 'win_rate': 0, 'avg_return': 0, 'max_return': 0, 'min_return': 0}

        total = len(reviews)
        wins = sum(1 for r in reviews if r.hit_target == 1)
        returns = [r.actual_return for r in reviews]

        return {
            'total': total,
            'win_rate': wins / total if total > 0 else 0,
            'avg_return': sum(returns) / total if total > 0 else 0,
            'max_return': max(returns) if returns else 0,
            'min_return': min(returns) if returns else 0,
        }


class StockCacheDB:
    """股票缓存数据库操作"""

    def __init__(self, session: Optional[Session] = None):
        self.session = session or get_session()

    def update_cache(
        self,
        code: str,
        name: Optional[str] = None,
        last_price: Optional[float] = None,
        change_pct: Optional[float] = None,
        volume: Optional[float] = None,
        turnover: Optional[float] = None,
        pe: Optional[float] = None,
        pb: Optional[float] = None,
        total_mv: Optional[float] = None,
        circ_mv: Optional[float] = None
    ) -> StockCache:
        """更新股票缓存"""
        cache = self.session.query(StockCache).filter(
            StockCache.code == code
        ).first()

        if cache:
            if name:
                cache.name = name
            if last_price:
                cache.last_price = last_price
            if change_pct:
                cache.change_pct = change_pct
            if volume:
                cache.volume = volume
            if turnover:
                cache.turnover = turnover
            if pe:
                cache.pe = pe
            if pb:
                cache.pb = pb
            if total_mv:
                cache.total_mv = total_mv
            if circ_mv:
                cache.circ_mv = circ_mv
            cache.updated_at = datetime.now()
        else:
            cache = StockCache(
                code=code,
                name=name,
                last_price=last_price,
                change_pct=change_pct,
                volume=volume,
                turnover=turnover,
                pe=pe,
                pb=pb,
                total_mv=total_mv,
                circ_mv=circ_mv
            )
            self.session.add(cache)

        self.session.commit()
        return cache

    def get_cache(self, code: str) -> Optional[StockCache]:
        """获取股票缓存"""
        return self.session.query(StockCache).filter(
            StockCache.code == code
        ).first()

    def get_all_cache(self) -> List[StockCache]:
        """获取所有缓存"""
        return self.session.query(StockCache).all()

    def clear_old_cache(self, hours: int = 24) -> int:
        """清理过期缓存"""
        expire_time = datetime.now() - timedelta(hours=hours)
        count = self.session.query(StockCache).filter(
            StockCache.updated_at < expire_time
        ).delete()
        self.session.commit()
        return count