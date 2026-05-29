# 股票投资闭环工具

一个命令行股票投资决策辅助系统，实现从选股到卖出的完整闭环。

## 功能特性

### 核心功能
- **盘后选股引擎**: 多维度筛选（技术面+基本面），输出候选股池
- **持仓实时监控**: 盘中实时刷新盈亏，自动触发止盈止损提醒
- **集合竞价监控**: 9:15-9:25监控候选股竞价数据
- **盘中异动扫描**: 放量突破、均线金叉、大单异动检测
- **复盘报告**: 统计胜率、平均收益，优化建议

### 通知方式
- 桌面弹窗通知
- 声音提醒
- 飞书机器人推送

## 技术栈

- Python 3.10+
- BaoStock (历史K线数据)
- 腾讯实时行情接口
- SQLite 数据库
- Rich + Typer (CLI界面)

## 安装

```bash
# 克隆仓库
git clone https://github.com/279458179/stock_tool.git
cd stock_tool

# 安装依赖
pip install -r requirements.txt

# 初始化
python main.py init
```

## 使用方法

### 添加持仓

```bash
python main.py pos add --code 600519 --cost 1800 --shares 100 --name "茅台"
```

系统自动计算：
- 止损价：成本价 × (1 - 5%) = 1710
- 止盈价：成本价 × (1 + 10%) = 1980

### 查看持仓

```bash
python main.py pos list
```

### 运行选股

```bash
python main.py select run --limit 5
```

### 启动持仓监控

```bash
python main.py monitor
```

实时显示持仓盈亏，触发止盈止损时自动提醒。

### 启动后台服务

```bash
python main.py daemon
```

定时任务：
- 09:15 集合竞价监控
- 09:30 持仓监控启动
- 10:30/14:00 盘中异动扫描
- 15:30 盘后选股
- 16:00 复盘报告

### 查看配置

```bash
python main.py config --show
```

## 配置说明

编辑 `config.yaml`：

```yaml
# 止盈止损配置
risk:
  default_stop_loss: -0.05    # 止损-5%
  default_take_profit: 0.10   # 止盈+10%
  position_alert: 0.03        # 盈亏±3%提醒

# 通知配置
notification:
  desktop: true
  sound: true
  feishu_webhook: ""          # 飞书机器人webhook
```

## 项目结构

```
stock_tool/
├── main.py                 # CLI入口
├── config.yaml             # 配置文件
├── requirements.txt        # 依赖包
├── database/
│   ├── models.py           # 数据模型
│   └── operations.py       # 数据库操作
├── data_sources/
│   ├── baostock_api.py     # BaoStock接口
│   └── tencent_realtime.py # 腾讯实时行情
├── engines/
│   ├── stock_selector.py   # 选股引擎
│   ├── position_tracker.py # 持仓监控
│   ├── auction_monitor.py  # 竞价监控
│   ├── scanner.py          # 异动扫描
│   └── review.py           # 复盘模块
├── strategies/
│   ├── base.py             # 策略基类
│   ├── technical.py        # 技术面策略
│   └── fundamental.py      # 基本面策略
├── notifications/
│   └ notifier.py           # 通知模块
└── scheduler/
│   └ jobs.py               # 定时任务
```

## 选股策略

### 技术面
- 均线多头排列（MA5 > MA10 > MA20）
- MACD金叉
- 放量突破（量比 > 2）
- 价格站上均线

### 基本面
- PE估值合理（PE < 30）
- ROE盈利能力（ROE > 10%）
- 净利润增长

## 数据源

- **BaoStock**: 免费、稳定的A股历史数据接口
- **腾讯实时行情**: 实时价格推送

## 注意事项

- 本工具仅供学习参考，不构成投资建议
- 股市有风险，投资需谨慎
- 建议先使用模拟盘验证策略

## License

MIT