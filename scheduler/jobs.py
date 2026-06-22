"""定时任务调度模块"""
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
import time
import os
import sys

# 确保项目路径在sys.path中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_config
from engines.stock_selector import StockSelector
from engines.position_tracker import PositionTracker
from engines.auction_monitor import AuctionMonitor
from engines.scanner import Scanner
from engines.review import ReviewEngine
from notifications.notifier import Notifier
from data_sources.tencent_realtime import TencentRealtimeAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SchedulerManager:
    """定时任务管理器"""

    def __init__(self):
        self.config = get_config()
        self.scheduler = BackgroundScheduler(timezone='Asia/Shanghai')
        self.notifier = Notifier()
        self.realtime_api = TencentRealtimeAPI()

    def setup_jobs(self):
        """配置定时任务"""
        # 1. 集合竞价监控 (09:15)
        self.scheduler.add_job(
            self._run_auction_monitor,
            CronTrigger(hour=9, minute=15, day_of_week='mon-fri', timezone='Asia/Shanghai'),
            id='auction_monitor',
            name='集合竞价监控'
        )

        # 1.5 早盘选股日报 (09:25) — 开盘前5分钟推送（含竞价过滤）
        self.scheduler.add_job(
            self._run_morning_report,
            CronTrigger(hour=9, minute=25, day_of_week='mon-fri', timezone='Asia/Shanghai'),
            id='morning_report',
            name='早盘选股日报（竞价过滤版）'
        )

        # 2. 盘中异动扫描第一次 (10:30)
        self.scheduler.add_job(
            self._run_scanner,
            CronTrigger(hour=10, minute=30, day_of_week='mon-fri', timezone='Asia/Shanghai'),
            id='scanner_first',
            name='盘中异动扫描(第一次)'
        )

        # 3. 盘中异动扫描第二次 (14:00)
        self.scheduler.add_job(
            self._run_scanner,
            CronTrigger(hour=14, minute=0, day_of_week='mon-fri', timezone='Asia/Shanghai'),
            id='scanner_second',
            name='盘中异动扫描(第二次)'
        )

        # 4. 盘后选股已删除（20:00）— 2026-06-05 改为9:25竞价选股
        # 原 stock_selection 任务已移除，不再盘后选股

        # 5. 复盘报告 (16:00)
        self.scheduler.add_job(
            self._run_review,
            CronTrigger(hour=16, minute=0, day_of_week='mon-fri', timezone='Asia/Shanghai'),
            id='review',
            name='复盘报告'
        )

        # 6. 每日持仓报告 (17:00)
        self.scheduler.add_job(
            self._send_daily_report,
            CronTrigger(hour=17, minute=0, day_of_week='mon-fri', timezone='Asia/Shanghai'),
            id='daily_report',
            name='每日报告'
        )

        logger.info("定时任务已配置完成")

    def start(self):
        """启动调度器"""
        self.setup_jobs()
        self.scheduler.start()
        logger.info("调度器已启动")

        # 打印任务列表
        jobs = self.scheduler.get_jobs()
        logger.info(f"当前共有{len(jobs)}个定时任务")
        for job in jobs:
            logger.info(f"  - {job.name}: {job.trigger}")

    def stop(self):
        """停止调度器"""
        self.scheduler.shutdown()
        logger.info("调度器已停止")

    def _run_morning_report(self):
        """运行早盘选股日报（09:25，开盘前5分钟）"""
        logger.info("运行早盘选股日报...")
        try:
            import baostock as bs
            from datetime import datetime, timedelta

            now = datetime.now()
            today_str = now.strftime("%Y年%m月%d日")
            weekday_map = {0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五"}
            weekday_str = weekday_map.get(now.weekday(), "")

            # 1. 获取选股结果（用最新收盘数据选股）
            selector = StockSelector()
            candidates = selector.run(limit=5)
            logger.info(f"选股完成，获得{len(candidates)}只候选股")

            # 2. 竞价过滤：拉实时行情，过滤异常开盘的股票
            candidates = self._apply_auction_filter(candidates)
            logger.info(f"竞价过滤后剩余{len(candidates)}只候选股")

            # 3. 获取大盘指数数据（最近3个交易日）
            indices_data = self._get_market_indices()

            # 4. 判断大盘方向
            market_direction, market_strategy, position_suggest = self._analyze_market(indices_data)

            # 5. 生成原因分析
            reason_analysis = self._generate_reason_analysis(indices_data)

            # 6. 格式化报告并推送
            report_md = self._format_morning_report(
                today_str=today_str,
                weekday_str=weekday_str,
                market_direction=market_direction,
                market_strategy=market_strategy,
                position_suggest=position_suggest,
                reason_analysis=reason_analysis,
                candidates=candidates,
                indices_data=indices_data,
            )

            self.notifier.send_alert(
                title=f"📋 Mac小股·今日操作简报",
                message=report_md,
                level="info"
            )
            logger.info("早盘选股日报已推送")

        except Exception as e:
            logger.error(f"早盘选股日报失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.notifier.send_alert(
                title="早报异常",
                message=f"早盘选股日报执行失败: {str(e)}",
                level="warning"
            )

    def _get_market_indices(self) -> dict:
        """获取三大指数最近3个交易日数据"""
        import baostock as bs
        from datetime import datetime, timedelta

        bs.login()
        indices = {
            '上证综指': 'sh.000001',
            '深证成指': 'sz.399001',
            '创业板指': 'sz.399006',
        }
        result = {}
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')

        for name, code in indices.items():
            df = bs.query_history_k_data_plus(code, 'date,close,pctChg,volume,amount',
                start_date=start_date, end_date=end_date, frequency='d', adjustflag='3')
            if df.error_code == '0':
                data = df.get_data()
                import pandas as pd
                for col in ['close', 'pctChg', 'volume', 'amount']:
                    if col in data.columns:
                        data[col] = pd.to_numeric(data[col], errors='coerce')
                if not data.empty:
                    result[name] = {
                        'code': code,
                        'data': data,
                        'latest': data.iloc[-1],
                    }

        bs.logout()
        return result

    def _analyze_market(self, indices_data: dict) -> tuple:
        """分析大盘方向"""
        if not indices_data:
            return '震荡', '稳健', '5成仓'

        latest = list(indices_data.values())[0]['latest']
        pct = latest.get('pctChg', 0)

        # 简单判断
        if pct > 0.5:
            return '上升', '积极', '7成仓'
        elif pct < -1.0:
            return '偏弱', '偏稳健，控制仓位', '5成仓'
        elif pct < -0.5:
            return '震荡偏弱', '偏稳健，等回调低吸', '5成仓'
        else:
            return '震荡', '稳健操作', '6成仓'

    def _generate_reason_analysis(self, indices_data: dict) -> list:
        """生成原因分析"""
        reasons = []
        if not indices_data:
            reasons.append("市场数据获取中，仅供参考")
            return reasons

        latest_idx = list(indices_data.values())[0]['latest']
        pct = latest_idx.get('pctChg', 0)
        volume = latest_idx.get('amount', 0)

        if pct < -1:
            reasons.append(f"三大指数全线下跌，量能{volume/1e8:.0f}亿，资金出逃信号明显")
        elif pct > 0.5:
            reasons.append(f"三大指数全线上涨，量能配合良好，做多情绪回暖")
        else:
            reasons.append(f"市场震荡整理，量能{'放大' if volume > 1.5e8 else '萎缩'}，观望情绪较浓")

        # 检查创业板
        if '创业板指' in indices_data:
            cr_pct = indices_data['创业板指']['latest'].get('pctChg', 0)
            if cr_pct < -1.5:
                reasons.append(f"创业板领跌{cr_pct:.1f}%，题材股承压，风格可能向价值蓝筹切换")
            elif cr_pct > 1.5:
                reasons.append(f"创业板领涨{cr_pct:.1f}%，成长股活跃，题材行情可期")

        reasons.append("今日开盘前请确认集合竞价情况，再决定是否跟进")
        return reasons

    def _format_morning_report(
        self,
        today_str: str,
        weekday_str: str,
        market_direction: str,
        market_strategy: str,
        position_suggest: str,
        reason_analysis: list,
        candidates: list,
        indices_data: dict,
    ) -> str:
        """格式化早盘选股日报"""
        lines = []
        lines.append(f"📋 **Mac小股·今日操作简报**")
        lines.append(f"🗓️ {today_str}（{weekday_str}）")
        lines.append("━━━━━ 第一部分：大盘研判 ━━━━━")
        lines.append(f"📊 大盘方向：**{market_direction}**")
        lines.append(f"💡 操作策略：**{market_strategy}**")
        lines.append(f"🔔 仓位建议：**{position_suggest}**")

        # 大盘指数
        if indices_data:
            lines.append("")
            lines.append("📈 最近交易日收盘数据：")
            for name, info in indices_data.items():
                latest = info['latest']
                lines.append(f"- {name} {latest['close']:.2f} **{latest['pctChg']:+.2f}%**")

        lines.append("━━━━━ 第二部分：原因分析 ━━━━━")
        lines.append("📰 影响大盘的主要因素：")
        for i, reason in enumerate(reason_analysis, 1):
            lines.append(f"{chr(0x245F + i)} {reason}")

        lines.append("━━━━━ 第三部分：重点股票 ━━━━━")

        if not candidates:
            lines.append("🎯 今日暂无符合条件的候选股，建议观望。")
        else:
            lines.append(f"🎯 今日重点（共{len(candidates)}只，进攻型，顺大盘方向）")
            lines.append("")

            for i, c in enumerate(candidates, 1):
                name = c.get('name', '?')
                code = c.get('code', '?')
                score = c.get('score', 0)
                last_close = c.get('last_close', 0)
                buy_low = c.get('buy_range_low', 0)
                buy_high = c.get('buy_range_high', 0)
                target = c.get('target_price', 0)
                stop_loss = c.get('stop_loss', 0)
                position = c.get('position_advice', '')
                reason = c.get('reason', '')

                # 计算买入数量（约1万元/只）
                shares = int(10000 / last_close / 100) * 100 if last_close > 0 else 0

                # 计算两档卖出价
                sell_half = target * 0.95  # 第一档
                sell_all = target          # 第二档

                lines.append(f"{chr(0x245F + i)} {name}（{code}） {reason}")
                lines.append(f"📍 现价参考：约{last_close:.2f}元（评分{score}）")
                lines.append(f"💰 买入价：激进{buy_high:.2f}元以下 / 稳健{buy_low:.2f}元以下")
                lines.append(f"🔢 买入数量：{shares}股（约{shares * last_close / 10000:.1f}万元）")
                lines.append(f"🎯 卖出价：{sell_half:.2f}元卖一半，{sell_all:.2f}元全卖")
                lines.append(f"🛡️ 止损价：{stop_loss:.2f}元")
                lines.append(f"⚠️ 适配大盘：{market_direction}")
                lines.append("")

        lines.append("⚠️ 风险提示：以上分析仅供参考，不构成投资建议，盈亏自负。")
        lines.append(f"📊 数据来源：BaoStock + stock_tool选股引擎（{datetime.now().strftime('%Y-%m-%d %H:%M')}）")

        return "\n".join(lines)

    def _apply_auction_filter(self, candidates: list) -> list:
        """
        竞价过滤：用腾讯实时接口拉候选股的当前价，过滤异常开盘的股票
        过滤规则：
        - 竞价涨幅 > 8% → 排除（追高风险）
        - 竞价涨幅 > 6% 且 评分 < 60 → 排除
        - 竞价跌幅 < -5% → 排除（可能有利空）
        """
        if not candidates:
            return candidates

        try:
            # 拉实时行情
            codes = [c['code'] for c in candidates]
            quotes = self.realtime_api.get_batch_quotes(codes)
            quote_map = {q['code']: q for q in quotes}

            filtered = []
            for c in candidates:
                code = c['code']
                q = quote_map.get(code, {})
                price = q.get('price', 0)
                last_close = q.get('last_close', 0)
                change_pct = (price - last_close) / last_close * 100 if last_close > 0 else 0

                # 记录实时数据到候选股
                c['current_price'] = price
                c['change_pct'] = change_pct
                c['last_close_realtime'] = last_close

                # 过滤规则
                if change_pct > 8:
                    logger.info(f"竞价过滤排除 {c['name']}({code}): 涨{change_pct:+.1f}% > 8%")
                    continue
                if change_pct > 6 and c.get('score', 0) < 60:
                    logger.info(f"竞价过滤排除 {c['name']}({code}): 涨{change_pct:+.1f}% 且评分{c.get('score')}<60")
                    continue
                if change_pct < -5:
                    logger.info(f"竞价过滤排除 {c['name']}({code}): 跌{change_pct:+.1f}% < -5%")
                    continue

                filtered.append(c)

            return filtered
        except Exception as e:
            logger.error(f"竞价过滤失败: {e}，返回原始候选股")
            # 过滤失败不阻塞，返回原始候选股
            return candidates

    def _run_auction_monitor(self):
        """运行竞价监控"""
        logger.info("启动集合竞价监控...")
        try:
            monitor = AuctionMonitor()
            # 只在竞价时间运行（9:15-9:25）
            now = datetime.now()
            if now.hour == 9 and 15 <= now.minute <= 25:
                monitor.start()
            else:
                logger.info(f"当前时间{now.strftime('%H:%M')}，不在竞价时段，跳过")
        except Exception as e:
            logger.error(f"竞价监控失败: {e}")
            self.notifier.send_alert(
                title="竞价监控异常",
                message=f"竞价监控执行失败: {str(e)}",
                level="warning"
            )

    def _run_scanner(self):
        """运行异动扫描"""
        logger.info("运行盘中异动扫描...")
        try:
            scanner = Scanner()
            results = scanner.scan()

            if results:
                logger.info(f"发现{len(results)}只异动股票")
                # 发送异动通知
                message_lines = [f"发现{len(results)}只异动股票："]
                for r in results[:5]:
                    message_lines.append(
                        f"{r['name']}({r['code']}): {r['type']} 评分{r['score']} 现价{r['price']}"
                    )
                self.notifier.send_alert(
                    title="盘中异动扫描",
                    message="\n".join(message_lines),
                    level="info"
                )
            else:
                logger.info("未发现符合条件的异动股票")

        except Exception as e:
            logger.error(f"异动扫描失败: {e}")
            self.notifier.send_alert(
                title="异动扫描异常",
                message=f"异动扫描执行失败: {str(e)}",
                level="warning"
            )

    def _run_stock_selection(self):
        """运行盘后选股"""
        logger.info("运行盘后选股...")
        try:
            selector = StockSelector()
            candidates = selector.run(limit=5)

            if candidates:
                logger.info(f"选股完成，输出{len(candidates)}只候选股")
                # 发送选股结果
                message_lines = ["📋 明日操作候选池\n"]
                for c in candidates:
                    message_lines.append(
                        f"{c['name']}({c['code']}) 评分{c['score']}\n"
                        f"  现价参考: 约{c.get('last_close', 0):.2f}元\n"
                        f"  买入区间: {c['buy_range_low']:.2f}-{c['buy_range_high']:.2f}元\n"
                        f"  目标价: {c['target_price']:.2f}元\n"
                        f"  止损价: {c['stop_loss']:.2f}元\n"
                        f"  {c['position_advice']}\n"
                        f"  理由: {c['reason']}"
                    )

                self.notifier.send_alert(
                    title="📋 明日操作候选池",
                    message="\n\n".join(message_lines),
                    level="info"
                )
            else:
                self.notifier.send_alert(
                    title="盘后选股完成",
                    message="今日未找到符合条件的候选股",
                    level="info"
                )

        except Exception as e:
            logger.error(f"盘后选股失败: {e}")
            self.notifier.send_alert(
                title="选股异常",
                message=f"盘后选股执行失败: {str(e)}",
                level="warning"
            )

    def _run_review(self):
        """运行复盘"""
        logger.info("运行复盘...")
        try:
            engine = ReviewEngine()
            engine.generate_report(days=7)
            logger.info("复盘完成")
        except Exception as e:
            logger.error(f"复盘失败: {e}")
            self.notifier.send_alert(
                title="复盘异常",
                message=f"复盘执行失败: {str(e)}",
                level="warning"
            )

    def _send_daily_report(self):
        """发送每日报告"""
        logger.info("发送每日报告...")
        try:
            from database.operations import PositionDB, CandidateDB, SignalDB

            position_db = PositionDB()
            candidate_db = CandidateDB()
            signal_db = SignalDB()

            positions = position_db.get_all_positions()
            signals = signal_db.get_today_signals()

            # 计算持仓盈亏
            tracker = PositionTracker()
            summary = tracker.get_position_summary()

            # 构建详细报告
            lines = []
            lines.append(f"📊 每日持仓报告")
            lines.append(f"{'━' * 25}")
            
            # 第一部分：总览
            lines.append(f"总持仓: {summary['total_positions']} 只")
            lines.append(f"总成本: {summary['total_cost']:,.2f} 元")
            lines.append(f"总市值: {summary['total_value']:,.2f} 元")
            profit = summary['total_profit']
            profit_pct = summary['total_profit_pct']
            profit_icon = "📈" if profit >= 0 else "📉"
            lines.append(f"{profit_icon} 总盈亏: {profit:+,.2f} 元 ({profit_pct:+.2f}%)")
            lines.append("")

            # 第二部分：持仓明细
            if positions:
                lines.append("━━━ 持仓明细 ━━━")
                # 获取实时行情
                codes = [p.code for p in positions]
                quotes = tracker.realtime_api.get_batch_quotes(codes)
                quote_map = {q['code']: q for q in quotes}

                # 构建持仓摘要列表
                pos_list = []
                for p in positions:
                    q = quote_map.get(p.code, {})
                    current = q.get('price', p.cost)
                    profit_val = (current - p.cost) * p.shares
                    profit_p = (current - p.cost) / p.cost * 100 if p.cost > 0 else 0
                    pos_list.append({
                        'name': p.name or '?',
                        'code': p.code,
                        'cost': p.cost,
                        'current': current,
                        'shares': p.shares,
                        'profit': profit_val,
                        'profit_pct': profit_p,
                        'stop_loss': p.stop_loss or 0,
                        'stop_profit': p.target_price or 0,
                    })

                # 按盈亏排序
                sorted_positions = sorted(pos_list, key=lambda x: x['profit_pct'], reverse=True)

                for p in sorted_positions:
                    name = p['name']
                    code = p['code']
                    cost = p['cost']
                    current = p['current']
                    shares = p['shares']
                    profit_val = p['profit']
                    profit_p = p['profit_pct']

                    icon = "🔴" if profit_val >= 0 else "🟢"
                    lines.append(f"{icon} {name}（{code}）")
                    lines.append(f"   成本{cost:.3f} → 现价{current:.3f} | {shares}股")
                    lines.append(f"   盈亏: {profit_val:+,.0f}元 ({profit_p:+.2f}%)")

                    # 止损止盈状态
                    stop_loss = p['stop_loss']
                    stop_profit = p['stop_profit']
                    dist_stop = (current - stop_loss) / stop_loss * 100 if stop_loss > 0 else 0
                    dist_target = (stop_profit - current) / current * 100 if stop_profit > 0 else 0

                    if profit_p >= 0:
                        lines.append(f"   🎯 距止盈{stop_profit:.2f}元还有{dist_target:.1f}%")
                    else:
                        lines.append(f"   🛡️ 距止损{stop_loss:.2f}元还有{dist_stop:.1f}%空间")
                    lines.append("")

                # 第三部分：最佳/最差
                best = sorted_positions[0]
                worst = sorted_positions[-1]
                lines.append("━━━ 今日表现 ━━━")
                lines.append(f"🏆 最佳: {best['name']} {best['profit_pct']:+.2f}%")
                lines.append(f"💀 最差: {worst['name']} {worst['profit_pct']:+.2f}%")

                # 盈亏分布
                profit_count = len([p for p in pos_list if p['profit'] >= 0])
                loss_count = len(pos_list) - profit_count
                lines.append(f"📊 盈亏比: 红{profit_count}绿{loss_count}")
                lines.append("")

            # 第四部分：今日信号
            stop_loss_count = len([s for s in signals if s.signal_type == 'stop_loss'])
            target_count = len([s for s in signals if s.signal_type == 'target'])
            alert_count = len([s for s in signals if s.signal_type == 'alert'])
            
            if stop_loss_count + target_count + alert_count > 0:
                lines.append("━━━ 今日信号 ━━━")
                lines.append(f"止损触发: {stop_loss_count} 次")
                lines.append(f"止盈触发: {target_count} 次")
                lines.append(f"预警信号: {alert_count} 次")
                lines.append("")

            # 第五部分：明日建议
            lines.append("━━━ 明日关注 ━━━")
            if profit_pct < -3:
                lines.append("⚠️ 整体亏损超3%，建议减仓观望")
            elif profit_pct < 0:
                lines.append("⚡ 小幅亏损，重点观察绿色个股是否止跌")
            else:
                lines.append("📈 整体盈利，持有待涨，注意止盈节奏")
            
            # 提醒重点关注股
            danger_stocks = [p for p in pos_list if p['profit_pct'] < -2]
            if danger_stocks:
                names = "/".join([p['name'] for p in danger_stocks])
                lines.append(f"⚠️ 重点关注: {names}（亏损超2%，注意止损）")
            
            lines.append("")
            lines.append(f"📊 数据来源: stock_tool持仓监控 · {datetime.now().strftime('%Y-%m-%d %H:%M')}")

            message = "\n".join(lines)

            self.notifier.send_alert(
                title="📊 每日持仓报告",
                message=message,
                level="info"
            )

        except Exception as e:
            logger.error(f"发送每日报告失败: {e}")

    def get_job_status(self) -> dict:
        """获取任务状态"""
        jobs = self.scheduler.get_jobs()
        status = {}
        for job in jobs:
            status[job.id] = {
                'name': job.name,
                'next_run': str(job.next_run_time),
                'trigger': str(job.trigger),
            }
        return status

    def pause_job(self, job_id: str):
        """暂停任务"""
        self.scheduler.pause_job(job_id)
        logger.info(f"任务{job_id}已暂停")

    def resume_job(self, job_id: str):
        """恢复任务"""
        self.scheduler.resume_job(job_id)
        logger.info(f"任务{job_id}已恢复")

    def run_job_now(self, job_id: str):
        """立即运行任务"""
        job = self.scheduler.get_job(job_id)
        if job:
            job.func()
            logger.info(f"任务{job_id}已手动触发")


def start_scheduler():
    """启动调度器"""
    manager = SchedulerManager()
    manager.start()

    # 保持运行
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        manager.stop()


if __name__ == "__main__":
    start_scheduler()
