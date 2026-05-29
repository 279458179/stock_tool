"""定时任务调度模块"""
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging

from stock_tool.config import get_config
from stock_tool.engines.stock_selector import StockSelector
from stock_tool.engines.position_tracker import PositionTracker
from stock_tool.engines.auction_monitor import AuctionMonitor
from stock_tool.engines.scanner import Scanner
from stock_tool.engines.review import ReviewEngine
from stock_tool.notifications.notifier import Notifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SchedulerManager:
    """定时任务管理器"""

    def __init__(self):
        self.config = get_config()
        self.scheduler = BackgroundScheduler()
        self.notifier = Notifier()

    def setup_jobs(self):
        """配置定时任务"""
        # 1. 集合竞价监控 (09:15)
        self.scheduler.add_job(
            self._run_auction_monitor,
            CronTrigger(hour=9, minute=15, day_of_week='mon-fri'),
            id='auction_monitor',
            name='集合竞价监控'
        )

        # 2. 持仓监控启动 (09:30)
        self.scheduler.add_job(
            self._start_position_monitor,
            CronTrigger(hour=9, minute=30, day_of_week='mon-fri'),
            id='position_monitor_start',
            name='持仓监控启动'
        )

        # 3. 盘中异动扫描第一次 (10:30)
        self.scheduler.add_job(
            self._run_scanner,
            CronTrigger(hour=10, minute=30, day_of_week='mon-fri'),
            id='scanner_first',
            name='盘中异动扫描(第一次)'
        )

        # 4. 盘中异动扫描第二次 (14:00)
        self.scheduler.add_job(
            self._run_scanner,
            CronTrigger(hour=14, minute=0, day_of_week='mon-fri'),
            id='scanner_second',
            name='盘中异动扫描(第二次)'
        )

        # 5. 盘后选股 (15:30)
        self.scheduler.add_job(
            self._run_stock_selection,
            CronTrigger(hour=15, minute=30, day_of_week='mon-fri'),
            id='stock_selection',
            name='盘后选股'
        )

        # 6. 复盘报告 (16:00)
        self.scheduler.add_job(
            self._run_review,
            CronTrigger(hour=16, minute=0, day_of_week='mon-fri'),
            id='review',
            name='复盘报告'
        )

        # 7. 每日报告发送 (17:00)
        self.scheduler.add_job(
            self._send_daily_report,
            CronTrigger(hour=17, minute=0, day_of_week='mon-fri'),
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

    def stop(self):
        """停止调度器"""
        self.scheduler.shutdown()
        logger.info("调度器已停止")

    def _run_auction_monitor(self):
        """运行竞价监控"""
        logger.info("启动集合竞价监控...")

        try:
            monitor = AuctionMonitor()
            monitor.start()
        except Exception as e:
            logger.error(f"竞价监控失败: {e}")
            self.notifier.send_alert(
                title="竞价监控异常",
                message=f"竞价监控执行失败: {str(e)}",
                level="warning"
            )

    def _start_position_monitor(self):
        """启动持仓监控"""
        logger.info("启动持仓监控...")

        # 持仓监控需要持续运行，这里只是启动标记
        self.notifier.send_alert(
            title="持仓监控启动",
            message="开盘时间已到，请启动持仓监控: stock-tool monitor",
            level="info"
        )

    def _run_scanner(self):
        """运行异动扫描"""
        logger.info("运行盘中异动扫描...")

        try:
            scanner = Scanner()
            results = scanner.scan(min_score=70)

            if results:
                logger.info(f"发现{len(results)}只异动股票")

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
                message_lines = ["今日选股结果："]
                for c in candidates:
                    message_lines.append(
                        f"{c['name']}({c['code']}) 评分{c['score']:.1f} "
                        f"建议买入{c['buy_range_low']:.2f}-{c['buy_range_high']:.2f}"
                    )

                self.notifier.send_alert(
                    title="盘后选股完成",
                    message="\n".join(message_lines),
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
            engine.update_review_data(days=1)
            stats = engine.generate_report(days=7)

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
            from stock_tool.database.operations import PositionDB, CandidateDB, SignalDB

            position_db = PositionDB()
            candidate_db = CandidateDB()
            signal_db = SignalDB()

            positions = position_db.get_all_positions()
            candidates = candidate_db.get_today_candidates()
            signals = signal_db.get_today_signals()

            # 计算持仓盈亏
            tracker = PositionTracker()
            summary = tracker.get_position_summary()

            report_data = {
                'candidates_count': len(candidates),
                'positions_count': len(positions),
                'total_profit': summary.get('total_profit', 0),
                'total_profit_pct': summary.get('total_profit_pct', 0),
                'stop_loss_count': len([s for s in signals if s.signal_type == 'stop_loss']),
                'target_count': len([s for s in signals if s.signal_type == 'target']),
            }

            self.notifier.send_daily_report(report_data)

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
        import time
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        manager.stop()


if __name__ == "__main__":
    start_scheduler()