"""持仓实时监控模块"""
import time
from typing import List, Dict, Any, Optional
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
import logging

from config import get_config
from data_sources.tencent_realtime import get_api, TencentRealtimeAPI
from database.operations import PositionDB, SignalDB
from notifications.notifier import Notifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
console = Console()


class PositionTracker:
    """持仓实时监控"""

    def __init__(self):
        self.config = get_config()
        self.realtime_api = get_api()
        self.position_db = PositionDB()
        self.signal_db = SignalDB()
        self.notifier = Notifier()
        self._running = False
        self._alerted_positions = set()  # 已提醒过的持仓

    def start_monitoring(self, refresh_interval: float = 1.0):
        """启动实时监控"""
        self._running = True

        console.print("[cyan]正在启动持仓监控...[/cyan]")

        # 获取持仓
        positions = self.position_db.get_all_positions()

        if not positions:
            console.print("[yellow]暂无持仓，请先添加持仓[/yellow]")
            return

        console.print(f"[green]监控{len(positions)}只持仓[/green]")

        codes = [p.code for p in positions]

        # 创建持仓信息映射
        position_map = {p.code: p for p in positions}

        with Live(self._build_display([], position_map), refresh_per_second=1) as live:
            while self._running:
                # 只在交易时间更新
                if self.realtime_api.is_trading_time():
                    # 获取实时行情
                    quotes = self.realtime_api.get_batch_quotes(codes)

                    # 更新显示
                    live.update(self._build_display(quotes, position_map))

                    # 检查触发条件
                    self._check_triggers(quotes, position_map)

                time.sleep(refresh_interval)

    def stop_monitoring(self):
        """停止监控"""
        self._running = False

    def _build_display(self, quotes: List[Dict[str, Any]], position_map: Dict[str, Any]) -> Panel:
        """构建显示面板"""
        table = Table(title="持仓实时监控")
        table.add_column("代码", style="cyan", width=8)
        table.add_column("名称", width=10)
        table.add_column("成本价", width=8)
        table.add_column("现价", width=8)
        table.add_column("盈亏", width=8)
        table.add_column("盈亏%", width=8)
        table.add_column("目标价", width=8)
        table.add_column("止损价", width=8)
        table.add_column("状态", width=8)

        total_profit = 0
        total_cost = 0

        for quote in quotes:
            code = quote['code']
            position = position_map.get(code)

            if not position:
                continue

            current_price = quote['price']
            cost_price = position.cost
            shares = position.shares

            # 计算盈亏
            profit = (current_price - cost_price) * shares
            profit_pct = (current_price - cost_price) / cost_price * 100

            total_profit += profit
            total_cost += cost_price * shares

            # 盈亏颜色
            if profit > 0:
                profit_style = "green"
                profit_text = f"+{profit:.2f}"
                profit_pct_text = f"+{profit_pct:.2f}%"
            else:
                profit_style = "red"
                profit_text = f"{profit:.2f}"
                profit_pct_text = f"{profit_pct:.2f}%"

            # 状态判断
            status = "正常"
            status_style = "white"

            if position.stop_loss and current_price <= position.stop_loss:
                status = "触发止损"
                status_style = "red bold"
            elif position.target_price and current_price >= position.target_price:
                status = "触发止盈"
                status_style = "green bold"
            elif profit_pct >= self.config.risk.position_alert * 100:
                status = "盈利提醒"
                status_style = "green"
            elif profit_pct <= -self.config.risk.position_alert * 100:
                status = "亏损提醒"
                status_style = "red"

            table.add_row(
                code,
                position.name or quote['name'] or "-",
                f"{cost_price:.2f}",
                f"{current_price:.2f}",
                f"[{profit_style}]{profit_text}[/{profit_style}]",
                f"[{profit_style}]{profit_pct_text}[/{profit_style}]",
                f"{position.target_price:.2f}" if position.target_price else "-",
                f"{position.stop_loss:.2f}" if position.stop_loss else "-",
                f"[{status_style}]{status}[/{status_style}]"
            )

        # 总盈亏
        if total_cost > 0:
            total_profit_pct = total_profit / total_cost * 100
            total_text = f"总盈亏: {total_profit:.2f} ({total_profit_pct:.2f}%)"
        else:
            total_text = "总盈亏: --"

        # 当前时间
        current_time = datetime.now().strftime("%H:%M:%S")

        return Panel(
            table,
            title=f"[bold cyan]持仓监控[/bold cyan] | [white]{current_time}[/white] | [yellow]{total_text}[/yellow]",
            border_style="cyan"
        )

    def _check_triggers(self, quotes: List[Dict[str, Any]], position_map: Dict[str, Any]):
        """检查触发条件"""
        for quote in quotes:
            code = quote['code']
            position = position_map.get(code)

            if not position:
                continue

            current_price = quote['price']
            cost_price = position.cost

            # 计算盈亏比例
            profit_pct = (current_price - cost_price) / cost_price

            # 检查止损
            if position.stop_loss and current_price <= position.stop_loss:
                if code not in self._alerted_positions:
                    self._trigger_stop_loss(code, position, current_price)
                    self._alerted_positions.add(code)

            # 检查止盈
            elif position.target_price and current_price >= position.target_price:
                if code not in self._alerted_positions:
                    self._trigger_target(code, position, current_price)
                    self._alerted_positions.add(code)

            # 检查盈亏提醒阈值
            elif abs(profit_pct) >= self.config.risk.position_alert:
                if code not in self._alerted_positions:
                    self._trigger_alert(code, position, current_price, profit_pct)
                    self._alerted_positions.add(code)

            # 如果价格恢复正常，清除提醒标记
            else:
                if code in self._alerted_positions:
                    # 检查是否不再触发止损/止盈
                    if position.stop_loss and current_price > position.stop_loss:
                        self._alerted_positions.discard(code)
                    if position.target_price and current_price < position.target_price:
                        self._alerted_positions.discard(code)

    def _trigger_stop_loss(self, code: str, position: Any, current_price: float):
        """触发止损提醒"""
        logger.warning(f"触发止损提醒: {code} 现价{current_price} 止损价{position.stop_loss}")

        # 记录信号
        self.signal_db.add_signal(
            code=code,
            name=position.name,
            signal_type='stop_loss',
            price=current_price,
            notes=f"触发止损价{position.stop_loss}"
        )

        # 发送通知
        loss_pct = (current_price - position.cost) / position.cost * 100
        self.notifier.send_alert(
            title="止损提醒",
            message=f"{position.name}({code})触发止损！\n"
                    f"现价: {current_price:.2f}\n"
                    f"止损价: {position.stop_loss:.2f}\n"
                    f"亏损: {loss_pct:.2f}%",
            level="critical"
        )

    def _trigger_target(self, code: str, position: Any, current_price: float):
        """触发止盈提醒"""
        logger.info(f"触发止盈提醒: {code} 现价{current_price} 目标价{position.target_price}")

        # 记录信号
        self.signal_db.add_signal(
            code=code,
            name=position.name,
            signal_type='target',
            price=current_price,
            notes=f"触发目标价{position.target_price}"
        )

        # 发送通知
        profit_pct = (current_price - position.cost) / position.cost * 100
        self.notifier.send_alert(
            title="止盈提醒",
            message=f"{position.name}({code})达到目标价！\n"
                    f"现价: {current_price:.2f}\n"
                    f"目标价: {position.target_price:.2f}\n"
                    f"盈利: {profit_pct:.2f}%",
            level="success"
        )

    def _trigger_alert(self, code: str, position: Any, current_price: float, profit_pct: float):
        """触发盈亏提醒"""
        logger.info(f"触发盈亏提醒: {code} 盈亏{profit_pct*100:.2f}%")

        # 记录信号
        signal_type = 'alert_profit' if profit_pct > 0 else 'alert_loss'
        self.signal_db.add_signal(
            code=code,
            name=position.name,
            signal_type=signal_type,
            price=current_price,
            notes=f"盈亏{profit_pct*100:.2f}%"
        )

        # 发送通知
        if profit_pct > 0:
            self.notifier.send_alert(
                title="盈利提醒",
                message=f"{position.name}({code})盈利{profit_pct*100:.2f}%！\n"
                        f"现价: {current_price:.2f}\n"
                        f"成本: {position.cost:.2f}",
                level="info"
            )
        else:
            self.notifier.send_alert(
                title="亏损提醒",
                message=f"{position.name}({code})亏损{abs(profit_pct)*100:.2f}%！\n"
                        f"现价: {current_price:.2f}\n"
                        f"成本: {position.cost:.2f}\n"
                        f"止损价: {position.stop_loss:.2f}",
                level="warning"
            )

    def get_position_summary(self) -> Dict[str, Any]:
        """获取持仓概要"""
        positions = self.position_db.get_all_positions()

        if not positions:
            return {
                'total_positions': 0,
                'total_cost': 0,
                'total_value': 0,
                'total_profit': 0,
                'positions': []
            }

        codes = [p.code for p in positions]
        quotes = self.realtime_api.get_batch_quotes(codes)
        quote_map = {q['code']: q for q in quotes}

        total_cost = 0
        total_value = 0
        position_list = []

        for position in positions:
            cost = position.cost * position.shares
            quote = quote_map.get(position.code)

            if quote:
                current_value = quote['price'] * position.shares
                profit = current_value - cost
                profit_pct = (quote['price'] - position.cost) / position.cost * 100
            else:
                current_value = cost
                profit = 0
                profit_pct = 0

            total_cost += cost
            total_value += current_value

            position_list.append({
                'code': position.code,
                'name': position.name,
                'cost': position.cost,
                'shares': position.shares,
                'current_price': quote['price'] if quote else position.cost,
                'value': current_value,
                'profit': profit,
                'profit_pct': profit_pct,
                'target_price': position.target_price,
                'stop_loss': position.stop_loss,
            })

        return {
            'total_positions': len(positions),
            'total_cost': total_cost,
            'total_value': total_value,
            'total_profit': total_value - total_cost,
            'total_profit_pct': (total_value - total_cost) / total_cost * 100 if total_cost > 0 else 0,
            'positions': position_list
        }

    def calculate_position_value(self, position: Any, current_price: float) -> float:
        """计算持仓市值"""
        return current_price * position.shares

    def calculate_profit_loss(self, position: Any, current_price: float) -> Dict[str, float]:
        """计算盈亏"""
        cost_value = position.cost * position.shares
        current_value = current_price * position.shares

        profit = current_value - cost_value
        profit_pct = (current_price - position.cost) / position.cost

        return {
            'profit': profit,
            'profit_pct': profit_pct,
            'cost_value': cost_value,
            'current_value': current_value
        }