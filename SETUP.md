# 股票投资闭环工具 - 安装配置指南

## 快速开始

### 1. 安装依赖

```bash
cd /Users/xiaohuozi/.openclaw/workspace-stock/stock_tool
python3 -m pip install -r requirements.txt
```

### 2. 初始化数据库

```bash
python3 main.py init
```

### 3. 配置飞书通知（重要）

要让系统推送通知到飞书，需要配置飞书机器人webhook：

#### 步骤：
1. 在飞书中创建一个自定义机器人
2. 获取webhook URL（格式：`https://open.feishu.cn/open-apis/bot/v2/hook/xxx`）
3. 编辑 `config.yaml`，填写webhook地址：

```yaml
notification:
  feishu_webhook: "https://open.feishu.cn/open-apis/bot/v2/hook/你的token"
```

#### 测试通知：

```bash
python3 main.py config --show
python3 main.py test  # 测试数据接口和通知
```

### 4. 启动后台服务

#### 方式一：前台运行（调试用）

```bash
python3 main.py daemon
```

#### 方式二：后台守护进程（生产环境）

```bash
# 加载launchd配置
launchctl load ~/Library/LaunchAgents/com.stock-tool.daemon.plist

# 查看状态
launchctl list | grep stock-tool

# 停止服务
launchctl unload ~/Library/LaunchAgents/com.stock-tool.daemon.plist
```

### 5. 手动运行命令

#### 选股

```bash
python3 main.py select run --limit 5
```

#### 持仓管理

```bash
# 添加持仓
python3 main.py pos add --code 600519 --cost 1800 --shares 100 --name "贵州茅台"

# 查看持仓
python3 main.py pos list

# 删除持仓
python3 main.py pos remove --code 600519
```

#### 候选池

```bash
# 查看候选
python3 main.py cand list

# 跳过某只
python3 main.py cand skip --code 600011
```

#### 持仓监控

```bash
python3 main.py monitor
```

#### 集合竞价

```bash
python3 main.py auction  # 9:15-9:25运行
```

#### 盘中异动扫描

```bash
python3 main.py scan
```

#### 复盘报告

```bash
python3 main.py review --days 7
```

## 定时任务说明

系统包含以下定时任务：

| 时间 | 任务 | 说明 |
|------|------|------|
| 09:15 | 集合竞价监控 | 监控候选股竞价数据 |
| 10:30 | 盘中异动扫描 | 第一次异动扫描 |
| 14:00 | 盘中异动扫描 | 第二次异动扫描 |
| 16:00 | 复盘报告 | 生成复盘统计 |
| 17:00 | 每日持仓报告 | 发送当日盈亏汇总 |
| 20:00 | 盘后选股 | 选出次日候选池 |

## 配置参数说明

### config.yaml

```yaml
# 选股器配置
selector:
  min_price: 5.0              # 最低价格5元（排除低价股）
  max_price: 50.0             # 最高价格50元
  min_score: 50.0             # 最低评分门槛
  min_signals: 2              # 最少共振信号数
  max_pct_1d: 8.0             # 追高过滤：1日涨幅>8%排除
  max_open_pct: 6.0           # 高开>6%且评分<60→剔除
  max_open_pct_hard: 8.0      # 高开>8%→一律剔除
  stock_pool: "hs300"         # 选股池：沪深300成分股

# 止盈止损
risk:
  default_stop_loss: -0.05    # 止损-5%
  default_take_profit: 0.10   # 止盈+10%
  position_alert: 0.03        # 盈亏±3%提醒
```

## 文件说明

| 文件/目录 | 说明 |
|-----------|------|
| `main.py` | CLI入口 |
| `config.yaml` | 配置文件 |
| `data/stock.db` | SQLite数据库 |
| `engines/stock_selector.py` | 选股引擎 |
| `engines/position_tracker.py` | 持仓监控 |
| `engines/auction_monitor.py` | 集合竞价监控 |
| `engines/scanner.py` | 盘中异动扫描 |
| `engines/review.py` | 复盘模块 |
| `scheduler/jobs.py` | 定时任务调度 |
| `notifications/notifier.py` | 通知模块（桌面+飞书） |
| `data_sources/` | 数据源接口 |
| `strategies/` | 选股策略 |
| `database/` | 数据库操作 |

## 注意事项

1. **飞书webhook必须配置**，否则通知只会发送到桌面
2. **BaoStock接口**需要网络访问国内服务器
3. **腾讯行情接口** `qt.gtimg.cn` 需要网络访问
4. **定时任务**在交易日（周一至周五）运行，周末自动跳过
5. **数据库**会自动创建在 `data/stock.db`

## 故障排查

### 数据接口测试

```bash
python3 main.py test
```

### 查看日志

```bash
tail -f logs/daemon.log
tail -f logs/daemon-error.log
```

### 检查定时任务状态

```bash
python3 -c "
from scheduler.jobs import SchedulerManager
manager = SchedulerManager()
manager.setup_jobs()
for job in manager.scheduler.get_jobs():
    print(f'{job.name}: {job.next_run_time}')
"
```
