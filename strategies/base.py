"""策略基类"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List
import pandas as pd


class BaseStrategy(ABC):
    """选股策略基类"""

    name: str = "base"
    description: str = "基础策略"

    @abstractmethod
    def evaluate(self, code: str, data: pd.DataFrame, **kwargs) -> Dict[str, Any]:
        """
        评估股票

        Args:
            code: 股票代码
            data: K线数据DataFrame
            **kwargs: 其他参数

        Returns:
            评估结果字典，包含:
            - score: 评分 (0-100)
            - passed: 是否通过筛选
            - signals: 信号列表
            - details: 详细信息
        """
        pass

    @abstractmethod
    def get_required_data(self) -> List[str]:
        """
        获取策略所需的数据字段

        Returns:
            数据字段列表
        """
        pass

    def calculate_score(self, signals: List[Dict[str, Any]]) -> float:
        """
        根据信号计算综合评分

        Args:
            signals: 信号列表，每个信号包含weight和value

        Returns:
            综合评分 (0-100)
        """
        if not signals:
            return 0

        total_weight = sum(s.get('weight', 1) for s in signals)
        total_score = sum(s.get('weight', 1) * s.get('score', 0) for s in signals)

        return total_score / total_weight if total_weight > 0 else 0

    def check_requirements(self, data: pd.DataFrame) -> bool:
        """
        检查数据是否满足策略需求

        Args:
            data: K线数据

        Returns:
            是否满足需求
        """
        required = self.get_required_data()
        missing = [r for r in required if r not in data.columns]

        if missing:
            return False

        return True


class StrategyResult:
    """策略结果"""

    def __init__(
        self,
        code: str,
        name: str = "",
        score: float = 0,
        passed: bool = False,
        signals: List[Dict[str, Any]] = [],
        details: Dict[str, Any] = {}
    ):
        self.code = code
        self.name = name
        self.score = score
        self.passed = passed
        self.signals = signals
        self.details = details

    def to_dict(self) -> Dict[str, Any]:
        return {
            'code': self.code,
            'name': self.name,
            'score': self.score,
            'passed': self.passed,
            'signals': self.signals,
            'details': self.details
        }


class StrategyManager:
    """策略管理器"""

    def __init__(self):
        self.strategies: List[BaseStrategy] = []

    def add_strategy(self, strategy: BaseStrategy):
        """添加策略"""
        self.strategies.append(strategy)

    def remove_strategy(self, strategy_name: str):
        """移除策略"""
        self.strategies = [s for s in self.strategies if s.name != strategy_name]

    def get_strategy(self, strategy_name: str) -> BaseStrategy:
        """获取策略"""
        for strategy in self.strategies:
            if strategy.name == strategy_name:
                return strategy
        return None

    def run_all(
        self,
        code: str,
        data: pd.DataFrame,
        **kwargs
    ) -> List[StrategyResult]:
        """
        运行所有策略

        Args:
            code: 股票代码
            data: K线数据
            **kwargs: 其他参数

        Returns:
            所有策略结果列表
        """
        results = []

        for strategy in self.strategies:
            if strategy.check_requirements(data):
                result = strategy.evaluate(code, data, **kwargs)
                results.append(StrategyResult(
                    code=code,
                    score=result.get('score', 0),
                    passed=result.get('passed', False),
                    signals=result.get('signals', []),
                    details=result.get('details', {})
                ))

        return results

    def get_combined_score(self, results: List[StrategyResult], weights: Dict[str, float] = None) -> float:
        """
        计算综合评分

        Args:
            results: 所有策略结果
            weights: 策略权重字典

        Returns:
            综合评分
        """
        if not results:
            return 0

        if weights is None:
            weights = {s.name: 1.0 / len(self.strategies) for s in self.strategies}

        total_score = 0
        total_weight = 0

        for strategy in self.strategies:
            for result in results:
                weight = weights.get(strategy.name, 0)
                total_score += result.score * weight
                total_weight += weight

        return total_score / total_weight if total_weight > 0 else 0