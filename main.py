"""股票投资闭环工具 - CLI入口"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.layout import Layout
from datetime import datetime
from typing import Optional

app = typer.Typer(help="股票投资闭环工具 - 从选股到卖出的完整决策辅助系统")
console = Console()


# 子命令组
position_app = typer.Typer(help="持仓管理命令")
candidate_app = typer.Typer(help="候选池管理命令")
select_app = typer.Typer(help="选股命令")

app.add_typer(position_app, name="pos")
app.add_typer(candidate_app, name="cand")
app.add_typer(select_app, name="select")


@app.command()
def init():
    """初始化数据库和配置"""
    from database.models import init_database

    console.print("[cyan]正在初始化数据库...[/cyan]")
    init_database()
    console.print("[green][OK] 数据库初始化完成[/green]")

    # 检查配置文件
    from config import get_config_path, Config
    config_path = get_config_path()

    if not config_path.exists():
        console.print("[yellow]配置文件不存在，正在创建默认配置...[/yellow]")
        default_config = Config()
        default_config.to_yaml(str(config_path))
        console.print(f"[green][OK] 配置文件已创建: {config_path}[/green]")
    else:
        console.print(f"[green][OK] 配置文件已存在: {config_path}[/green]")

    console.print(Panel("[bold green]初始化完成！[/bold green]\n\n可以使用以下命令开始:\n  python main.py pos add --code 600519 --cost 1800 --shares 100\n  python main.py select run\n  python main.py monitor", title="股票投资闭环工具"))


@position_app.command("add")
def add_position(
    code: str = typer.Option(..., "--code", "-c", help="股票代码，如600519"),
    cost: float = typer.Option(..., "--cost", help="成本价"),
    shares: int = typer.Option(..., "--shares", "-n", help="持仓数量"),
    target: Optional[float] = typer.Option(None, "--target", "-t", help="目标卖出价"),
    stop: Optional[float] = typer.Option(None, "--stop", "-s", help="止损价"),
    name: Optional[str] = typer.Option(None, "--name", help="股票名称")
):
    """添加持仓"""
    from database.operations import PositionDB
    from config import get_config

    config = get_config()

    # 如果没有设置止损止盈，使用默认值
    if stop is None:
        stop = cost * (1 + config.risk.default_stop_loss)
    if target is None:
        target = cost * (1 + config.risk.default_take_profit)

    db = PositionDB()
    position = db.add_position(
        code=code,
        name=name,
        cost=cost,
        shares=shares,
        target_price=target,
        stop_loss=stop
    )

    console.print(f"[green][OK] 添加持仓成功[/green]")
    console.print(f"  股票代码: {code}")
    console.print(f"  成本价: {cost}")
    console.print(f"  持仓数量: {shares}")
    console.print(f"  目标价: {target:.2f}")
    console.print(f"  止损价: {stop:.2f}")


@position_app.command("remove")
def remove_position(
    code: str = typer.Option(..., "--code", "-c", help="股票代码")
):
    """删除持仓"""
    from database.operations import PositionDB

    db = PositionDB()
    if db.remove_position(code):
        console.print(f"[green][OK] 已删除持仓: {code}[/green]")
    else:
        console.print(f"[red][FAIL] 未找到持仓: {code}[/red]")


@position_app.command("list")
def list_positions():
    """查看所有持仓"""
    from database.operations import PositionDB

    db = PositionDB()
    positions = db.get_all_positions()

    if not positions:
        console.print("[yellow]暂无持仓[/yellow]")
        return

    table = Table(title="持仓列表")
    table.add_column("代码", style="cyan")
    table.add_column("名称")
    table.add_column("成本价")
    table.add_column("数量")
    table.add_column("目标价")
    table.add_column("止损价")
    table.add_column("买入日期")

    for p in positions:
        table.add_row(
            p.code,
            p.name or "-",
            str(p.cost),
            str(p.shares),
            str(p.target_price) if p.target_price else "-",
            str(p.stop_loss) if p.stop_loss else "-",
            p.buy_date or "-"
        )

    console.print(table)


@candidate_app.command("list")
def list_candidates(
    status: str = typer.Option("pending", "--status", "-s", help="状态筛选: pending/bought/skipped/all")
):
    """查看候选池"""
    from database.operations import CandidateDB
    from database.models import Candidate

    db = CandidateDB()

    if status == "all":
        candidates = db.get_all_candidates()
    elif status == "pending":
        candidates = db.get_pending_candidates()
    else:
        candidates = db.session.query(Candidate).filter(
            Candidate.status == status
        ).all()

    if not candidates:
        console.print(f"[yellow]暂无{status}状态的候选股[/yellow]")
        return

    table = Table(title="候选池")
    table.add_column("代码", style="cyan")
    table.add_column("名称")
    table.add_column("选入日期")
    table.add_column("买入区间")
    table.add_column("目标价")
    table.add_column("止损价")
    table.add_column("评分")
    table.add_column("状态")

    for c in candidates:
        buy_range = f"{c.buy_range_low:.2f}-{c.buy_range_high:.2f}" if c.buy_range_low and c.buy_range_high else "-"
        table.add_row(
            c.code,
            c.name or "-",
            c.select_date or "-",
            buy_range,
            str(c.target_price) if c.target_price else "-",
            str(c.stop_loss) if c.stop_loss else "-",
            str(c.score) if c.score else "-",
            c.status
        )

    console.print(table)


@candidate_app.command("skip")
def skip_candidate(
    code: str = typer.Option(..., "--code", "-c", help="股票代码")
):
    """跳过候选股"""
    from database.operations import CandidateDB

    db = CandidateDB()
    if db.update_status(code, "skipped"):
        console.print(f"[green][OK] 已跳过候选股: {code}[/green]")
    else:
        console.print(f"[red][FAIL] 未找到候选股: {code}[/red]")


@select_app.command("run")
def run_selection(
    date: Optional[str] = typer.Option(None, "--date", "-d", help="选股日期，默认今天"),
    limit: int = typer.Option(5, "--limit", "-l", help="输出候选股数量")
):
    """运行选股引擎"""
    from engines.stock_selector import StockSelector

    console.print("[cyan]正在运行选股引擎...[/cyan]")
    console.print("[yellow]获取全市场股票数据...[/yellow]")

    selector = StockSelector()
    candidates = selector.run(limit=limit)

    if not candidates:
        console.print("[yellow]今日未找到符合条件的候选股[/yellow]")
        return

    console.print(f"[green][OK] 找到{len(candidates)}只候选股[/green]")

    table = Table(title=f"今日候选股 ({date or datetime.now().strftime('%Y-%m-%d')})")
    table.add_column("代码", style="cyan")
    table.add_column("名称")
    table.add_column("评分", style="green")
    table.add_column("建议买入价")
    table.add_column("目标价")
    table.add_column("止损价")
    table.add_column("仓位建议")
    table.add_column("选入理由")

    for c in candidates:
        table.add_row(
            c['code'],
            c['name'],
            str(c['score']),
            f"{c['buy_range_low']:.2f}-{c['buy_range_high']:.2f}",
            f"{c['target_price']:.2f}",
            f"{c['stop_loss']:.2f}",
            c['position_advice'],
            c['reason'][:30] + "..." if len(c['reason']) > 30 else c['reason']
        )

    console.print(table)


@app.command()
def monitor(
    refresh: int = typer.Option(1, "--refresh", "-r", help="刷新间隔(秒)")
):
    """启动实时持仓监控"""
    from engines.position_tracker import PositionTracker

    console.print("[cyan]启动持仓实时监控...[/cyan]")
    console.print("[yellow]按Ctrl+C退出[/yellow]")

    tracker = PositionTracker()

    try:
        tracker.start_monitoring(refresh_interval=refresh)
    except KeyboardInterrupt:
        console.print("\n[yellow]监控已停止[/yellow]")


@app.command()
def daemon():
    """启动后台服务(定时任务)"""
    from scheduler.jobs import start_scheduler

    console.print("[cyan]启动后台服务...[/cyan]")
    console.print("[yellow]定时任务列表:[/yellow]")
    console.print("  09:15 - 集合竞价监控")
    console.print("  09:30 - 持仓监控启动")
    console.print("  10:30 - 盘中异动扫描(第一次)")
    console.print("  14:00 - 盘中异动扫描(第二次)")
    console.print("  15:30 - 盘后选股")
    console.print("  16:00 - 复盘报告")
    console.print("\n[yellow]按Ctrl+C停止[/yellow]")

    try:
        start_scheduler()
    except KeyboardInterrupt:
        console.print("\n[yellow]后台服务已停止[/yellow]")


@app.command()
def review(
    days: int = typer.Option(7, "--days", "-d", help="复盘天数")
):
    """生成复盘报告"""
    from database.operations import ReviewDB
    from engines.review import ReviewEngine

    console.print(f"[cyan]正在生成{days}天复盘报告...[/cyan]")

    db = ReviewDB()
    stats = db.get_stats(days)

    console.print(Panel(
        f"[bold]胜率: [/bold]{stats['win_rate']*100:.1f}%\n"
        f"[bold]平均收益: [/bold]{stats['avg_return']*100:.2f}%\n"
        f"[bold]最大收益: [/bold]{stats['max_return']*100:.2f}%\n"
        f"[bold]最大亏损: [/bold]{stats['min_return']*100:.2f}%\n"
        f"[bold]总操作数: [/bold]{stats['total']}",
        title="复盘统计"
    ))

    # 生成详细复盘
    engine = ReviewEngine()
    engine.generate_report(days)


@app.command()
def auction():
    """启动集合竞价监控"""
    from engines.auction_monitor import AuctionMonitor

    console.print("[cyan]启动集合竞价监控...[/cyan]")
    console.print("[yellow]监控时间: 09:15-09:25[/yellow]")

    monitor = AuctionMonitor()
    monitor.start()


@app.command()
def scan():
    """运行盘中异动扫描"""
    from engines.scanner import Scanner

    console.print("[cyan]运行盘中异动扫描...[/cyan]")

    scanner = Scanner()
    results = scanner.scan()

    if not results:
        console.print("[yellow]未发现符合条件的异动股票[/yellow]")
        return

    table = Table(title="异动股票")
    table.add_column("代码", style="cyan")
    table.add_column("名称")
    table.add_column("异动类型")
    table.add_column("评分")
    table.add_column("当前价")
    table.add_column("详情")

    for r in results:
        table.add_row(
            r['code'],
            r['name'],
            r['type'],
            str(r['score']),
            str(r['price']),
            r['detail']
        )

    console.print(table)


@app.command()
def config(
    show: bool = typer.Option(False, "--show", help="显示当前配置"),
    edit: bool = typer.Option(False, "--edit", help="编辑配置文件")
):
    """配置管理"""
    from config import get_config, get_config_path, Config

    if show:
        config = get_config()
        console.print(Panel(
            f"[bold]数据源: [/bold]{config.data_source.primary}/{config.data_source.realtime}\n"
            f"[bold]策略权重: [/bold]技术{config.strategy.technical_weight} + 基本{config.strategy.fundamental_weight} + 资金{config.strategy.capital_weight}\n"
            f"[bold]止损: [/bold]{config.risk.default_stop_loss*100}%\n"
            f"[bold]止盈: [/bold]{config.risk.default_take_profit*100}%\n"
            f"[bold]提醒阈值: [/bold]{config.risk.position_alert*100}%\n"
            f"[bold]桌面通知: [/bold]{config.notification.desktop}\n"
            f"[bold]声音提醒: [/bold]{config.notification.sound}\n"
            f"[bold]飞书webhook: [/bold]{config.notification.feishu_webhook or '未配置'}",
            title="当前配置"
        ))

    if edit:
        config_path = get_config_path()
        console.print(f"[yellow]配置文件路径: {config_path}[/yellow]")
        console.print("[yellow]请手动编辑配置文件[/yellow]")


@app.command()
def test():
    """测试数据接口"""
    console.print("[cyan]测试数据接口...[/cyan]")

    # 测试腾讯实时行情
    console.print("\n[yellow]测试腾讯实时行情接口[/yellow]")
    from data_sources.tencent_realtime import TencentRealtimeAPI
    api = TencentRealtimeAPI()

    # 测试获取茅台实时行情
    quote = api.get_realtime_quote("600519")
    if quote:
        console.print(f"[green][OK] 成功获取600519行情[/green]")
        console.print(f"  名称: {quote['name']}")
        console.print(f"  价格: {quote['price']}")
        console.print(f"  涨跌幅: {quote['change_pct']}%")
    else:
        console.print("[red][FAIL] 获取行情失败[/red]")

    # 测试BaoStock
    console.print("\n[yellow]测试BaoStock接口[/yellow]")
    from data_sources.baostock_api import BaoStockAPI
    bs_api = BaoStockAPI()

    if bs_api.login():
        console.print("[green][OK] BaoStock登录成功[/green]")

        # 测试获取K线数据
        k_data = bs_api.get_recent_k_data("sh.600519", days=10)
        if not k_data.empty:
            console.print(f"[green][OK] 成功获取K线数据，共{len(k_data)}条[/green]")
            console.print(f"  最新收盘价: {k_data['close'].iloc[-1]}")
        else:
            console.print("[red][FAIL] K线数据获取失败[/red]")

        bs_api.logout()
    else:
        console.print("[red][FAIL] BaoStock登录失败[/red]")

    console.print("\n[green]测试完成[/green]")


if __name__ == "__main__":
    app()