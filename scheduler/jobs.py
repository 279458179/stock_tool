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

    def setup_jobs(self):
        """配置定时任务"""
        # 1. 集合竞价监控 (09:15)
        self.scheduler.add_job(
            self._run_auction_monitor,
            CronTrigger(hour=9, minute=15, day_of_week='mon-fri', timezone='Asia/Shanghai'),
            id='auction_monitor',
            name='集合竞价监控'
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

        # 4. 盘后选股 (20:00)
        self.scheduler.add_job(
            self._run_stock_selection,
            CronTrigger(hour=20, minute=0, day_of_week='mon-fri', timezone='Asia/Shanghai'),
            id='stock_selection',
            name='盘后选股（次日候选池）'
        )

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

            message = f"📊 每日持仓报告\n"
            message += f"总持仓: {summary['total_positions']} 只\n"
            message += f"总成本: {summary['total_cost']:.2f} 元\n"
            message += f"总市值: {summary['total_value']:.2f} 元\n"
            message += f"总盈亏: {summary['total_profit']:.2f} 元 ({summary['total_profit_pct']:.2f}%)\n\n"

            # 今日信号
            stop_loss = len([s for s in signals if s.signal_type == 'stop_loss'])
            targets = len([s for s in signals if s.signal_type == 'target'])
            message += f"今日止损: {stop_loss} 次\n"
            message += f"今日止盈: {targets} 次\n"

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
