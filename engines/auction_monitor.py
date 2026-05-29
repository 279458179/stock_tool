"""集合竞价监控模块"""
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
import logging

from config import get_config
from data_sources.tencent_realtime import get_api, TencentRealtimeAPI
from data_sources.baostock_api import get_api as get_baostock_api
from database.operations import CandidateDB
from notifications.notifier import Notifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
console = Console()


class AuctionMonitor:
    """集合竞价监控器"""

    def __init__(self):
        self.config = get_config()
        self.realtime_api = get_api()
        self.baostock_api = get_baostock_api()
        self.candidate_db = CandidateDB()
        self.notifier = Notifier()
        self._running = False

    def start(self):
        """启动竞价监控"""
        self._running = True

        console.print("[cyan]集合竞价监控启动[/cyan]")

        # 获取今日候选股
        candidates = self.candidate_db.get_today_candidates()

        if not candidates:
            console.print("[yellow]今日暂无候选股[/yellow]")
            return

        console.print(f"[green]监控{len(candidates)}只候选股[/green]")

        codes = [c.code for c in candidates]
        candidate_map = {c.code: c for c in candidates}

        # 获取昨日收盘价作为基准
        baseline_prices = self._get_baseline_prices(codes)

        # 竞价监控循环（9:15-9:25）
        start_time = datetime.now().replace(hour=9, minute=15, second=0)
        end_time = datetime.now().replace(hour=9, minute=25, second=0)

        while self._running:
            current_time = datetime.now()

            # 检查是否在竞价时间
            if current_time < start_time:
                wait_seconds = (start_time - current_time).seconds
                console.print(f"[yellow]等待竞价开始，还需等待{wait_seconds}秒[/yellow]")
                time.sleep(wait_seconds)
                continue

            if current_time > end_time:
                console.print("[yellow]竞价时间结束[/yellow]")
                # 发送竞价结果汇总
                self._send_auction_summary()
                break

            # 获取竞价数据
            auction_data = self.realtime_api.get_batch_auction_data(codes)

            # 显示竞价数据
            self._display_auction(auction_data, candidate_map, baseline_prices)

            time.sleep(3)  # 3秒刷新一次

    def stop(self):
        """停止监控"""
        self._running = False

    def _get_baseline_prices(self, codes: List[str]) -> Dict[str, float]:
        """获取基准价格（昨日收盘价）"""
        baseline = {}

        for code in codes:
            # 尝试从实时行情获取昨日收盘价
            quote = self.realtime_api.get_realtime_quote(code)
            if quote and quote.get('last_close', 0) > 0:
                baseline[code] = quote['last_close']
                continue

            # 从K线数据获取
            k_data = self.baostock_api.get_recent_k_data(f"sh.{code}" if code.startswith('6') else f"sz.{code}", days=5)
            if not k_data.empty:
                baseline[code] = k_data['close'].iloc[-2]  # 前一天的收盘价

        return baseline

    def _display_auction(
        self,
        auction_data: List[Dict[str, Any]],
        candidate_map: Dict[str, Any],
        baseline_prices: Dict[str, float]
    ):
        """显示竞价数据"""
        table = Table(title="集合竞价监控")
        table.add_column("代码", style="cyan", width=8)
        table.add_column("名称", width=10)
        table.add_column("竞价价", width=8)
        table.add_column("竞价涨幅", width=10)
        table.add_column("信号", width=10)
        table.add_column("建议", width=15)

        results = []

        for data in auction_data:
            code = data['code']
            candidate = candidate_map.get(code)
            baseline = baseline_prices.get(code, data['last_close'])

            auction_price = data['auction_price']
            change_pct = data['auction_change_pct']

            # 判断信号
            signal, advice = self._analyze_auction_signal(
                auction_price,
                change_pct,
                candidate,
                baseline
            )

            # 信号颜色
            if signal == 'green':
                signal_style = "green bold"
            elif signal == 'red':
                signal_style = "red bold"
            else:
                signal_style = "yellow"

            table.add_row(
                code,
                data['name'] or candidate.name or "-",
                f"{auction_price:.2f}",
                f"[{signal_style}]{change_pct:.2f}%[{signal_style}]",
                f"[{signal_style}]{'可买' if signal == 'green' else '跳过' if signal == 'red' else '观察'}[{signal_style}]",
                advice[:15]
            )

            results.append({
                'code': code,
                'name': data['name'],
                'auction_price': auction_price,
                'auction_change_pct': change_pct,
                'signal': signal,
                'advice': advice
            })

        current_time = datetime.now().strftime("%H:%M:%S")
        console.print(Panel(table, title=f"[cyan]集合竞价监控[/cyan] | [white]{current_time}[/white]"))

        # 存储结果用于汇总
        self._auction_results = results

    def _analyze_auction_signal(
        self,
        auction_price: float,
        change_pct: float,
        candidate: Any,
        baseline: float
    ) -> tuple:
        """分析竞价信号"""
        # 竞价强度判断
        # 1. 竞价涨幅是否在买入区间内
        # 2. 竞价是否有成交量支持
        # 3. 竞价涨幅是否异常（过大或过小）

        buy_range_low = candidate.buy_range_low if candidate else baseline * 0.98
        buy_range_high = candidate.buy_range_high if candidate else baseline * 1.02

        # 竞价价格在买入区间内
        if buy_range_low <= auction_price <= buy_range_high:
            # 涨幅合理（-2%到+5%）
            if -2 <= change_pct <= 5:
                return 'green', "竞价符合买入区间"
            elif change_pct > 5:
                return 'red', "竞价涨幅过大，可能追高"
            else:
                return 'yellow', "竞价跌幅较大，观察"

        # 竞价价格高于买入区间
        elif auction_price > buy_range_high:
            if change_pct > 8:
                return 'red', "竞价涨幅过高，不建议追"
            else:
                return 'yellow', "竞价略高于区间，可观察"

        # 竞价价格低于买入区间
        else:
            if change_pct < -5:
                return 'red', "竞价跌幅过大，可能有风险"
            else:
                return 'green', "竞价低于区间，有机会"

    def _send_auction_summary(self):
        """发送竞价汇总"""
        if not hasattr(self, '_auction_results'):
            return

        green_stocks = [r for r in self._auction_results if r['signal'] == 'green']
        red_stocks = [r for r in self._auction_results if r['signal'] == 'red']

        console.print("\n[cyan]竞价结果汇总[/cyan]")

        if green_stocks:
            console.print("[green]可考虑买入[/green]")
            for stock in green_stocks:
                console.print(f"  {stock['name']}({stock['code']}): 竞价涨幅{stock['auction_change_pct']:.2f}%")

        if red_stocks:
            console.print("[red]建议跳过[/red]")
            for stock in red_stocks:
                console.print(f"  {stock['name']}({stock['code']}): 竞价涨幅{stock['auction_change_pct']:.2f}%")

        # 发送飞书通知
        self.notifier.send_auction_alert(self._auction_results)


class AuctionAnalyzer:
    """竞价分析器"""

    def analyze_auction_pattern(self, auction_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析竞价模式

        Args:
            auction_data: 竞价数据

        Returns:
            分析结果
        """
        auction_price = auction_data.get('auction_price', 0)
        last_close = auction_data.get('last_close', 0)
        auction_volume = auction_data.get('auction_volume', 0)

        # 计算竞价涨幅
        change_pct = (auction_price - last_close) / last_close * 100 if last_close > 0 else 0

        # 分析竞价强度
        strength = self._calculate_strength(change_pct, auction_volume)

        # 判断竞价意图
        intent = self._determine_intent(auction_price, last_close, change_pct)

        return {
            'strength': strength,
            'intent': intent,
            'change_pct': change_pct,
            'auction_price': auction_price,
            'recommendation': self._get_recommendation(strength, intent)
        }

    def _calculate_strength(self, change_pct: float, volume: float) -> str:
        """计算竞价强度"""
        if change_pct >= 5 and volume > 10000:
            return 'strong_buy'
        elif change_pct >= 3:
            return 'moderate_buy'
        elif change_pct <= -5 and volume > 10000:
            return 'strong_sell'
        elif change_pct <= -3:
            return 'moderate_sell'
        else:
            return 'neutral'

    def _determine_intent(self, auction_price: float, last_close: float, change_pct: float) -> str:
        """判断竞价意图"""
        if change_pct > 3:
            return '看多'
        elif change_pct < -3:
            return '看空'
        else:
            return '观望'

    def _get_recommendation(self, strength: str, intent: str) -> str:
        """获取建议"""
        if strength == 'strong_buy':
            return '竞价强势，但需警惕开盘后回调'
        elif strength == 'moderate_buy':
            return '竞价温和上涨，可考虑买入'
        elif strength == 'strong_sell':
            return '竞价大幅下跌，不建议买入'
        elif strength == 'moderate_sell':
            return '竞价下跌，需观察开盘走势'
        else:
            return '竞价平稳，可按计划执行'