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
        self._alerted_positions = set()  # 已提醒过的持仓 (止损/止盈)
        self._profit_alerts = {}  # {code: set(已触发的盈利级别)} 分级止盈
        self._high_prices = {}  # {code: 盘中最高价} 回落止盈跟踪
        self._price_history = {}  # {code: [(time, price), ...]} 急拉检测
        self._sell_advice_sent = {}  # {code: 已发送的卖出建议级别}

    def start_monitoring(self, refresh_interval: float = 1.0):
        """启动实时监控"""
        import sys
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

        is_tty = sys.stdout.isatty()

        if is_tty:
            # TTY模式：使用Live实时显示
            with Live(self._build_display([], position_map), refresh_per_second=1) as live:
                while self._running:
                    if self.realtime_api.is_trading_time():
                        quotes = self.realtime_api.get_batch_quotes(codes)
                        live.update(self._build_display(quotes, position_map))
                        self._check_triggers(quotes, position_map)
                    else:
                        logger.debug("非交易时段，跳过")
                    time.sleep(refresh_interval)
        else:
            # 后台模式（nohup/cron）：纯日志，不用Live
            logger.info(f"后台监控模式（非TTY），监控{len(codes)}只: {codes}")
            while self._running:
                if self.realtime_api.is_trading_time():
                    quotes = self.realtime_api.get_batch_quotes(codes)
                    self._check_triggers(quotes, position_map)
                    # 每10次打印一次摘要，避免日志过多
                    if not hasattr(self, '_loop_count'):
                        self._loop_count = 0
                    self._loop_count += 1
                    if self._loop_count % 10 == 0:
                        logger.info(f"监控运行中，已检查{self._loop_count}次")
                else:
                    if not hasattr(self, '_non_trading_logged'):
                        logger.info("非交易时段，等待开盘...")
                        self._non_trading_logged = True
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
            code = self._normalize_code(quote['code'])
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

    def _normalize_code(self, code: str) -> str:
        """统一代码格式：API返回纯数字→转为 sh.600025 格式"""
        if '.' in code:
            return code
        if code.startswith('6'):
            return f'sh.{code}'
        elif code.startswith('0') or code.startswith('3'):
            return f'sz.{code}'
        elif code.startswith('4') or code.startswith('8'):
            return f'bj.{code}'
        return code

    def _check_triggers(self, quotes: List[Dict[str, Any]], position_map: Dict[str, Any]):
        """检查触发条件 — 止损 + 分级止盈 + 急拉预警 + 回落止盈"""
        for quote in quotes:
            code = self._normalize_code(quote['code'])
            position = position_map.get(code)

            if not position:
                continue

            current_price = quote['price']
            cost_price = position.cost
            profit_pct = (current_price - cost_price) / cost_price
            now = datetime.now()

            # === 1. 更新盘中最高价（回落止盈跟踪） ===
            if code not in self._high_prices or current_price > self._high_prices[code]:
                self._high_prices[code] = current_price

            # === 2. 更新价格历史（急拉检测） ===
            if code not in self._price_history:
                self._price_history[code] = []
            # 保留最近5分钟数据（先过滤，再append，避免当前数据影响急拉判断）
            cutoff = now.timestamp() - 300
            self._price_history[code] = [(t, p) for t, p in self._price_history[code] if t.timestamp() >= cutoff]
            self._price_history[code].append((now, current_price))

            # === 3. 止损（最高优先级） ===
            if position.stop_loss and current_price <= position.stop_loss:
                if code not in self._alerted_positions:
                    self._trigger_stop_loss(code, position, current_price)
                    self._alerted_positions.add(code)
                continue

            # === 4. 分级止盈提醒（赚钱核心！） ===
            if profit_pct > 0:
                if code not in self._profit_alerts:
                    self._profit_alerts[code] = set()

                # +3% 关注级
                if profit_pct >= 0.03 and 3 not in self._profit_alerts[code]:
                    self._trigger_profit_alert(code, position, current_price, profit_pct, 3, '关注级')
                    self._profit_alerts[code].add(3)

                # +5% 卖一半级
                if profit_pct >= 0.05 and 5 not in self._profit_alerts[code]:
                    self._trigger_profit_alert(code, position, current_price, profit_pct, 5, '卖一半')
                    self._profit_alerts[code].add(5)

                # +8% 清仓级
                if profit_pct >= 0.08 and 8 not in self._profit_alerts[code]:
                    self._trigger_profit_alert(code, position, current_price, profit_pct, 8, '建议清仓')
                    self._profit_alerts[code].add(8)

                # +10% 强制卖出级
                if profit_pct >= 0.10 and 10 not in self._profit_alerts[code]:
                    self._trigger_profit_alert(code, position, current_price, profit_pct, 10, '强烈建议卖出')
                    self._profit_alerts[code].add(10)

            # === 5. 回落止盈（冲高回落保护利润） ===
            high = self._high_prices.get(code, current_price)
            if profit_pct > 0.02:  # 曾盈利2%以上就启用回落保护
                drop_from_high = (high - current_price) / high
                if drop_from_high >= 0.015 and profit_pct >= 0.02:  # 从高点回落1.5%且仍盈利2%+
                    alert_key = f'drop_{high:.2f}'
                    if code not in self._sell_advice_sent or alert_key not in str(self._sell_advice_sent.get(code, '')):
                        self._trigger_pullback_alert(code, position, current_price, high, profit_pct, drop_from_high)
                        self._sell_advice_sent[code] = alert_key

            # === 6. 急拉预警（5分钟内涨超3%可能是主力拉高出货） ===
            spike = self._check_price_spike(code)
            if spike and profit_pct > 0:
                self._trigger_spike_alert(code, position, current_price, spike, profit_pct)

            # === 7. 亏损关注（-3%/-5%） ===
            if profit_pct <= -0.05:
                if 'loss_5' not in self._profit_alerts.get(code, set()):
                    self._trigger_loss_alert(code, position, current_price, profit_pct, 5)
                    if code not in self._profit_alerts:
                        self._profit_alerts[code] = set()
                    self._profit_alerts[code].add('loss_5')
            elif profit_pct <= -0.03:
                if 'loss_3' not in self._profit_alerts.get(code, set()):
                    self._trigger_loss_alert(code, position, current_price, profit_pct, 3)
                    if code not in self._profit_alerts:
                        self._profit_alerts[code] = set()
                    self._profit_alerts[code].add('loss_3')

        # === 8. 组合级亏损告警（总资产亏损超3%强制建议减仓） ===
        self._check_portfolio_loss(quotes, position_map)

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

    def _check_price_spike(self, code: str) -> Optional[float]:
        """检测5分钟内是否急拉超3%"""
        history = self._price_history.get(code, [])
        if len(history) < 2:
            return None
        oldest_time, oldest_price = history[0]
        latest_time, latest_price = history[-1]
        if latest_price > 0 and oldest_price > 0:
            spike_pct = (latest_price - oldest_price) / oldest_price
            if spike_pct >= 0.03:
                return spike_pct
        return None

    def _trigger_profit_alert(self, code: str, position: Any, current_price: float,
                                profit_pct: float, level: int, advice: str):
        """分级止盈提醒"""
        shares = position.shares
        profit = (current_price - position.cost) * shares
        profit_value = profit * 0.5 if level >= 5 else profit  # 5%以上建议卖一半的金额

        if level == 3:
            title = "📈 盈利关注"
            message = (f"{position.name}({code}) 浮盈+{profit_pct*100:.1f}%！\n"
                      f"现价: {current_price:.2f} | 成本: {position.cost:.2f}\n"
                      f"浮盈: +{profit:.0f}元\n"
                      f"👀 关注走势，准备止盈计划")
        elif level == 5:
            title = "💰 卖一半锁利润"
            sell_shares = shares // 2
            message = (f"{position.name}({code}) 浮盈+{profit_pct*100:.1f}%！\n"
                      f"现价: {current_price:.2f} | 成本: {position.cost:.2f}\n"
                      f"浮盈: +{profit:.0f}元\n"
                      f"💰 建议卖一半锁利润：{sell_shares}股（约{sell_shares * current_price:.0f}元）\n"
                      f"剩余{shares - sell_shares}股可博更高收益")
        elif level == 8:
            title = "🔥 清仓建议"
            message = (f"{position.name}({code}) 浮盈+{profit_pct*100:.1f}%！\n"
                      f"现价: {current_price:.2f} | 成本: {position.cost:.2f}\n"
                      f"浮盈: +{profit:.0f}元\n"
                      f"🔥 建议清仓或留小仓位！利润已经很好了")
        else:  # 10%
            title = "⚠️ 强烈建议卖出"
            message = (f"{position.name}({code}) 浮盈+{profit_pct*100:.1f}%！\n"
                      f"现价: {current_price:.2f} | 成本: {position.cost:.2f}\n"
                      f"浮盈: +{profit:.0f}元\n"
                      f"⚠️ 强烈建议卖出！10%利润很难得，落袋为安")

        logger.info(f"分级止盈 {level}%: {code} 现价{current_price}")
        self.signal_db.add_signal(code=code, name=position.name, signal_type='profit_alert',
            price=current_price, notes=f"盈利{profit_pct*100:.1f}%, {advice}")
        self.notifier.send_alert(title=title, message=message, level="success")

    def _trigger_pullback_alert(self, code: str, position: Any, current_price: float,
                                  high_price: float, profit_pct: float, drop_pct: float):
        """冲高回落止盈提醒"""
        shares = position.shares
        profit = (current_price - position.cost) * shares
        lost_from_high = (high_price - current_price) * shares

        message = (f"{position.name}({code}) 冲高回落！\n"
                  f"盘中高点: {high_price:.2f} | 现价: {current_price:.2f}\n"
                  f"从高点回落: -{drop_pct*100:.1f}%（-{lost_from_high:.0f}元）\n"
                  f"当前浮盈: +{profit:.0f}元（+{profit_pct*100:.1f}%）\n"
                  f"💡 建议考虑卖出锁定利润，别让它跑了")

        logger.info(f"回落止盈: {code} 高点{high_price} 现价{current_price}")
        self.signal_db.add_signal(code=code, name=position.name, signal_type='pullback',
            price=current_price, notes=f"从{high_price}回落{drop_pct*100:.1f}%")
        self.notifier.send_alert(title="📉 冲高回落", message=message, level="warning")

    def _trigger_spike_alert(self, code: str, position: Any, current_price: float,
                              spike_pct: float, profit_pct: float):
        """急拉预警"""
        shares = position.shares
        profit = (current_price - position.cost) * shares

        message = (f"{position.name}({code}) 5分钟内急拉+{spike_pct*100:.1f}%！\n"
                  f"现价: {current_price:.2f} | 成本: {position.cost:.2f}\n"
                  f"浮盈: +{profit:.0f}元\n"
                  f"⚡ 急拉可能是主力拉高出货，注意观察量能\n"
                  f"如果量能跟不上，建议逢高减仓")

        logger.info(f"急拉预警: {code} 5分钟+{spike_pct*100:.1f}%")
        self.signal_db.add_signal(code=code, name=position.name, signal_type='spike',
            price=current_price, notes=f"5分钟急拉+{spike_pct*100:.1f}%")
        self.notifier.send_alert(title="⚡ 急拉预警", message=message, level="info")

    def _trigger_loss_alert(self, code: str, position: Any, current_price: float,
                             profit_pct: float, level: int):
        """亏损提醒 — 升级：-3%关注→-5%建议减仓→-7%强制建议清仓"""
        shares = position.shares
        loss = (current_price - position.cost) * shares
        distance_to_stop = (current_price - position.stop_loss) / position.stop_loss * 100 if position.stop_loss else 999

        if level == 3:
            # -3% 关注级
            title = "📉 亏损关注"
            message = (f"{position.name}({code}) 浮亏{profit_pct*100:.1f}%\n"
                      f"现价: {current_price:.2f} | 成本: {position.cost:.2f}\n"
                      f"浮亏: {loss:.0f}元\n"
                      f"👀 关注走势，距止损价{position.stop_loss:.2f}还有{distance_to_stop:.1f}%\n"
                      f"💡 如果继续下跌，-5%时建议减仓，-7%时必须清仓")
        elif level == 5:
            # -5% 建议减仓级（升级）
            sell_shares = shares // 2
            title = "⚠️ 建议减仓一半"
            message = (f"{position.name}({code}) 浮亏{profit_pct*100:.1f}%！\n"
                      f"现价: {current_price:.2f} | 成本: {position.cost:.2f}\n"
                      f"浮亏: {loss:.0f}元\n"
                      f"⚠️ 建议减仓一半锁定风险：卖出{sell_shares}股（约{sell_shares * current_price:.0f}元）\n"
                      f"剩余{shares - sell_shares}股观察，距止损价{position.stop_loss:.2f}还有{distance_to_stop:.1f}%\n"
                      f"🚨 如果跌破止损价{position.stop_loss:.2f}，必须清仓！")
        else:
            # -7% 强制建议清仓（升级）
            title = "🚨 强烈建议清仓"
            message = (f"{position.name}({code}) 浮亏{profit_pct*100:.1f}%！\n"
                      f"现价: {current_price:.2f} | 成本: {position.cost:.2f}\n"
                      f"浮亏: {loss:.0f}元\n"
                      f"🚨 强烈建议立即清仓！{shares}股（约{shares * current_price:.0f}元）\n"
                      f"已接近/达到止损价{position.stop_loss:.2f}，再跌就是硬亏了\n"
                      f"⚡ 不要硬扛，及时止损是保住本金的唯一方式")

        logger.info(f"亏损提醒 {level}%: {code} 现价{current_price}")
        self.signal_db.add_signal(code=code, name=position.name, signal_type='loss_alert',
            price=current_price, notes=f"亏损{profit_pct*100:.1f}%")
        self.notifier.send_alert(title=title, message=message, level="warning")

    # 组合级亏损告警跟踪
    _portfolio_loss_alerted = {}

    def _check_portfolio_loss(self, quotes: List[Dict[str, Any]], position_map: Dict[str, Any]):
        """组合级亏损告警：总持仓亏损超总资产3%强制建议减仓"""
        total_cost = 0
        total_value = 0

        for quote in quotes:
            code = self._normalize_code(quote['code'])
            position = position_map.get(code)
            if not position:
                continue
            total_cost += position.cost * position.shares
            total_value += quote['price'] * position.shares

        if total_cost == 0:
            return

        portfolio_loss_pct = (total_value - total_cost) / total_cost

        # 总亏损超3% → 强制建议减仓
        if portfolio_loss_pct <= -0.03:
            alert_key = 'loss_3'
            if alert_key not in self._portfolio_loss_alerted:
                self._portfolio_loss_alerted[alert_key] = True
                loss_value = total_cost - total_value
                message = (f"⚠️ 组合级风险告警！\n"
                          f"总持仓成本: {total_cost:,.0f}元\n"
                          f"当前市值: {total_value:,.0f}元\n"
                          f"总浮亏: -{loss_value:,.0f}元 ({portfolio_loss_pct*100:.1f}%)\n"
                          f"🚨 建议立即减仓！整体亏损已超3%\n"
                          f"💡 不要硬扛，保住本金是第一要务\n"
                          f"📉 弱势行情下，空仓也是策略")
                logger.warning(f"组合亏损{portfolio_loss_pct*100:.1f}%，触发减仓告警")
                self.notifier.send_alert(title="🚨 组合亏损告警", message=message, level="critical")
        elif portfolio_loss_pct > -0.01:
            # 亏损回到1%以内，重置告警
            if 'loss_3' in self._portfolio_loss_alerted:
                del self._portfolio_loss_alerted['loss_3']

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
        # API返回的代码是纯数字，需转为 sh.600025 格式才能匹配
        quote_map = {self._normalize_code(q['code']): q for q in quotes}

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