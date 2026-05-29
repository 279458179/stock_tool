"""复盘模块"""
from typing import List, Dict, Any
from datetime import datetime, timedelta
import logging
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from config import get_config
from data_sources.baostock_api import get_api
from database.operations import ReviewDB, CandidateDB, SignalDB

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
console = Console()


class ReviewEngine:
    """复盘引擎"""

    def __init__(self):
        self.config = get_config()
        self.baostock_api = get_api()
        self.review_db = ReviewDB()
        self.candidate_db = CandidateDB()
        self.signal_db = SignalDB()

    def generate_report(self, days: int = 7):
        """生成复盘报告"""
        console.print(f"[cyan]正在生成{days}天复盘报告...[/cyan]")

        # 1. 获取复盘记录
        reviews = self.review_db.get_reviews_by_days(days)

        # 2. 获取信号统计（按天数获取）
        from datetime import timedelta
        from database.models import Signal
        start_date = (datetime.now() - timedelta(days=days)).date()
        signals = self.signal_db.session.query(Signal).filter(
            Signal.triggered_at >= start_date
        ).all()

        # 3. 获取候选股状态
        candidates = self.candidate_db.get_all_candidates()

        # 4. 统计数据
        stats = self._calculate_statistics(reviews)

        # 5. 显示报告
        self._display_report(stats, reviews)

        # 6. 优化建议
        self._generate_optimization_suggestions(stats)

        return stats

    def _calculate_statistics(self, reviews: List[Any]) -> Dict[str, Any]:
        """计算统计数据"""
        if not reviews:
            return {
                'total': 0,
                'win_count': 0,
                'loss_count': 0,
                'win_rate': 0,
                'avg_return': 0,
                'max_return': 0,
                'min_return': 0,
                'total_return': 0,
                'sharpe': 0,
            }

        total = len(reviews)
        wins = [r for r in reviews if r.hit_target == 1]
        losses = [r for r in reviews if r.hit_target == 0]

        returns = [r.actual_return for r in reviews]

        return {
            'total': total,
            'win_count': len(wins),
            'loss_count': len(losses),
            'win_rate': len(wins) / total if total > 0 else 0,
            'avg_return': sum(returns) / total if total > 0 else 0,
            'max_return': max(returns) if returns else 0,
            'min_return': min(returns) if returns else 0,
            'total_return': sum(returns),
            'positive_returns': [r for r in returns if r > 0],
            'negative_returns': [r for r in returns if r < 0],
        }

    def _display_report(self, stats: Dict[str, Any], reviews: List[Any]):
        """显示复盘报告"""
        # 统计面板
        console.print(Panel(
            f"[bold]胜率: [/bold][{'green' if stats['win_rate'] >= 0.5 else 'red'}]{stats['win_rate']*100:.1f}%[/{'green' if stats['win_rate'] >= 0.5 else 'red'}]\n"
            f"[bold]平均收益: [/bold][{'green' if stats['avg_return'] >= 0 else 'red'}]{stats['avg_return']*100:.2f}%[/{'green' if stats['avg_return'] >= 0 else 'red'}]\n"
            f"[bold]最大收益: [/bold][green]{stats['max_return']*100:.2f}%[/green]\n"
            f"[bold]最大亏损: [/bold][red]{stats['min_return']*100:.2f}%[/red]\n"
            f"[bold]总操作数: [/bold]{stats['total']}\n"
            f"[bold]盈利次数: [/bold][green]{stats['win_count']}[/green]\n"
            f"[bold]亏损次数: [/bold][red]{stats['loss_count']}[/red]",
            title="[cyan]复盘统计[/cyan]"
        ))

        # 详细记录表
        if reviews:
            table = Table(title="复盘记录")
            table.add_column("代码", style="cyan", width=8)
            table.add_column("选入日期", width=10)
            table.add_column("选入价格", width=8)
            table.add_column("实际收益", width=10)
            table.add_column("是否达标", width=8)

            for r in reviews[:20]:  # 显示前20条
                return_color = 'green' if r.actual_return >= 0 else 'red'
                hit_color = 'green' if r.hit_target == 1 else 'red'

                table.add_row(
                    r.code,
                    r.select_date,
                    f"{r.select_price:.2f}" if r.select_price else "-",
                    f"[{return_color}]{r.actual_return*100:.2f}%[/{return_color}]",
                    f"[{hit_color}]{'达标' if r.hit_target == 1 else '未达标'}[{hit_color}]"
                )

            console.print(table)

    def _generate_optimization_suggestions(self, stats: Dict[str, Any]):
        """生成优化建议"""
        console.print("\n[cyan]优化建议[/cyan]")

        suggestions = []

        # 根据胜率给出建议
        if stats['win_rate'] < 0.4:
            suggestions.append("胜率偏低，建议：\n  1. 提高选股筛选标准\n  2. 增加基本面分析权重\n  3. 检查止损执行情况")

        elif stats['win_rate'] < 0.5:
            suggestions.append("胜率一般，建议：\n  1. 优化技术面指标参数\n  2. 加强止盈纪律")

        elif stats['win_rate'] >= 0.6:
            suggestions.append("胜率良好，继续保持当前策略")

        # 根据收益给出建议
        if stats['avg_return'] < 0:
            suggestions.append("平均收益为负，建议：\n  1. 严格执行止损\n  2. 避免追高买入\n  3. 提高持仓管理")

        # 根据最大亏损给出建议
        if stats['min_return'] < -0.1:
            suggestions.append(f"最大亏损{stats['min_return']*100:.1f}%过大，建议：\n  1. 缩小止损范围\n  2. 分散持仓")

        # 显示建议
        for suggestion in suggestions:
            console.print(f"[yellow]{suggestion}[/yellow]")

    def update_review_data(self, days: int = 1):
        """更新复盘数据"""
        from database.models import Candidate
        # 获取候选股
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        candidates = self.candidate_db.session.query(Candidate).filter(
            Candidate.select_date >= start_date
        ).all()

        for candidate in candidates:
            # 获取当前价格
            code = candidate.code
            k_data = self.baostock_api.get_recent_k_data(
                f"sh.{code}" if code.startswith('6') else f"sz.{code}",
                days=days + 5
            )

            if k_data.empty:
                continue

            current_price = k_data['close'].iloc[-1]
            select_price = candidate.buy_range_low or candidate.buy_range_high

            if not select_price:
                continue

            # 计算实际收益
            actual_return = (current_price - select_price) / select_price

            # 判断是否达标
            hit_target = 1 if actual_return >= 0 else 0

            # 添加复盘记录
            self.review_db.add_review(
                code=code,
                name=candidate.name,
                candidate_id=candidate.id,
                select_date=candidate.select_date,
                select_price=select_price,
                actual_return=actual_return,
                hit_target=hit_target,
                notes=f"候选股{candidate.status}"
            )

    def get_performance_by_stock(self, code: str) -> Dict[str, Any]:
        """获取单只股票表现"""
        from database.models import ReviewRecord
        reviews = self.review_db.session.query(ReviewRecord).filter(
            ReviewRecord.code == code
        ).all()

        if not reviews:
            return {'total': 0, 'avg_return': 0, 'win_rate': 0}

        returns = [r.actual_return for r in reviews]
        wins = sum(1 for r in reviews if r.hit_target == 1)

        return {
            'total': len(reviews),
            'avg_return': sum(returns) / len(reviews),
            'win_rate': wins / len(reviews),
            'max_return': max(returns),
            'min_return': min(returns),
        }

    def mark_bad_stocks(self, threshold: float = -0.05):
        """标记踩坑股票"""
        reviews = self.review_db.get_reviews_by_days(30)

        bad_stocks = []

        for review in reviews:
            if review.actual_return < threshold:
                bad_stocks.append({
                    'code': review.code,
                    'name': review.name,
                    'return': review.actual_return,
                    'select_date': review.select_date,
                })

        console.print(f"[red]踩坑股票列表（收益低于{threshold*100}%）[/red]")

        if bad_stocks:
            table = Table(title="踩坑股票")
            table.add_column("代码", style="cyan")
            table.add_column("名称")
            table.add_column("收益率")
            table.add_column("选入日期")

            for stock in bad_stocks:
                table.add_row(
                    stock['code'],
                    stock['name'],
                    f"[red]{stock['return']*100:.2f}%[/red]",
                    stock['select_date']
                )

            console.print(table)

        return bad_stocks


class BacktestEngine:
    """回测引擎"""

    def __init__(self):
        self.baostock_api = get_api()

    def run_backtest(
        self,
        strategy: callable,
        start_date: str,
        end_date: str,
        initial_capital: float = 100000
    ) -> Dict[str, Any]:
        """
        运行策略回测

        Args:
            strategy: 选股策略函数
            start_date: 开始日期
            end_date: 结束日期
            initial_capital: 初始资金

        Returns:
            回测结果
        """
        console.print(f"[cyan]开始回测: {start_date} - {end_date}[/cyan]")

        # 简化回测逻辑
        # 实际需要更复杂的回测框架

        trades = []
        capital = initial_capital

        # 这里只是示例框架
        # 实际实现需要：
        # 1. 按日期遍历
        # 2. 每天运行选股
        # 3. 模拟买入卖出
        # 4. 计算收益

        return {
            'initial_capital': initial_capital,
            'final_capital': capital,
            'total_return': (capital - initial_capital) / initial_capital,
            'trades': trades,
            'win_rate': 0,
            'max_drawdown': 0,
            'sharpe_ratio': 0,
        }

    def calculate_metrics(self, returns: List[float]) -> Dict[str, float]:
        """计算回测指标"""
        if not returns:
            return {}

        import numpy as np

        returns_array = np.array(returns)

        # 年化收益
        avg_return = returns_array.mean() * 252

        # 年化波动
        volatility = returns_array.std() * np.sqrt(252)

        # 夏普比率（假设无风险利率3%）
        sharpe = (avg_return - 0.03) / volatility if volatility > 0 else 0

        # 最大回撤
        cumulative = np.cumprod(1 + returns_array)
        max_cumulative = np.maximum.accumulate(cumulative)
        drawdowns = (cumulative - max_cumulative) / max_cumulative
        max_drawdown = drawdowns.min()

        return {
            'annualized_return': avg_return,
            'volatility': volatility,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
        }