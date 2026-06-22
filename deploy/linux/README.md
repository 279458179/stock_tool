# stock_tool Linux 部署指南

## 快速部署（一键）

```bash
# 在 Linux 机器上执行：
curl -fsSL https://raw.githubusercontent.com/279458179/stock_tool/master/deploy/linux/deploy.sh | bash

# 或带飞书凭据：
curl -fsSL https://raw.githubusercontent.com/279458179/stock_tool/master/deploy/linux/deploy.sh | bash -s -- \
  --feishu-app-id cli_a976b8xxxxx \
  --feishu-app-secret YOUR_SECRET \
  --feishu-open-id ou_5f71ffaa82d43a84b54b3a06ed009054
```

## 手动部署

```bash
# 1. 克隆代码
git clone https://github.com/279458179/stock_tool.git /opt/stock_tool
cd /opt/stock_tool

# 2. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置飞书通知（必须）
mkdir -p ~/.openclaw
cat > ~/.openclaw/openclaw.json << 'EOF'
{
  "channels": {
    "feishu": {
      "domain": "feishu",
      "appId": "cli_a976b8xxxxx",
      "appSecret": "YOUR_APP_SECRET",
      "accounts": {
        "stock": {
          "appId": "cli_a976b8xxxxx",
          "appSecret": "YOUR_APP_SECRET"
        }
      },
      "openId": "ou_5f71ffaa82d43a84b54b3a06ed009054"
    }
  }
}
EOF

# 5. 安装 systemd 服务
cp deploy/linux/stock-tool.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now stock-tool

# 6. 验证
systemctl status stock-tool
journalctl -u stock-tool -f
```

## 定时任务（自动）

systemd 服务启动后，APScheduler 会自动执行：

| 时间 | 任务 | 说明 |
|------|------|------|
| 09:15 | 集合竞价监控 | 监控竞价异动 |
| 09:25 | 早盘选股日报 | 选股+大盘研判+飞书推送 |
| 10:30 | 盘中异动扫描(1) | 强势股扫描 |
| 14:00 | 盘中异动扫描(2) | 午后异动 |
| 16:00 | 复盘报告 | 对比推荐vs实际 |
| 17:00 | 每日持仓报告 | 持仓盈亏汇总 |

## 手动命令

```bash
cd /opt/stock_tool
source venv/bin/activate

python3 main.py select run     # 手动选股
python3 main.py monitor        # 持仓监控（前台）
python3 main.py daemon         # 启动所有定时任务
python3 main.py pos list       # 查看持仓
python3 main.py scan           # 盘中异动扫描
python3 main.py review         # 复盘报告
```

## 目录结构

```
/opt/stock_tool/
├── main.py              # 入口
├── config.py            # 配置
├── config.yaml          # 策略参数
├── requirements.txt     # 依赖
├── engines/             # 核心引擎
│   ├── stock_selector.py    # 选股引擎
│   ├── position_tracker.py  # 持仓监控
│   ├── scanner.py           # 盘中扫描
│   └── review.py            # 复盘引擎
├── data_sources/        # 数据源
│   ├── baostock_api.py      # BaoStock（K线/财务）
│   └── tencent_realtime.py  # 腾讯行情（实时）
├── notifications/       # 通知
│   └── notifier.py          # 飞书API通知
├── scheduler/           # 定时任务
│   └── jobs.py              # APScheduler任务定义
├── data/                # 数据库
│   └── stock.db             # SQLite（持仓+候选）
├── logs/                # 日志
└── deploy/linux/        # Linux部署文件
    ├── deploy.sh
    ├── stock-tool.service
    └── README.md
```

## 飞书凭据获取

从 Mac 上复制 `~/.openclaw/openclaw.json` 中的飞书配置：
- `appId`: 飞书应用ID
- `appSecret`: 飞书应用密钥
- `openId`: 接收通知的用户ID

## 常见问题

**Q: 服务启动失败？**
```bash
journalctl -u stock-tool -n 50 --no-pager
```

**Q: 飞书通知不工作？**
检查 `~/.openclaw/openclaw.json` 是否存在且凭据正确。

**Q: BaoStock 连接失败？**
BaoStock 需要网络连接到 baostock.com，检查防火墙。

**Q: 时区不对？**
系统时区需设为 Asia/Shanghai：
```bash
timedatectl set-timezone Asia/Shanghai
```
