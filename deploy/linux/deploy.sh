#!/bin/bash
# stock_tool Linux 一键部署脚本
# 用法: bash deploy.sh [--feishu-app-id ID] [--feishu-app-secret SECRET] [--feishu-open-id OPENID]
set -e

INSTALL_DIR="/opt/stock_tool"
REPO_URL="https://github.com/279458179/stock_tool.git"
PYTHON_MIN="3.10"

echo "=========================================="
echo "  📈 stock_tool Linux 部署"
echo "=========================================="

# 解析参数
FEISHU_APP_ID=""
FEISHU_APP_SECRET=""
FEISHU_OPEN_ID=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --feishu-app-id) FEISHU_APP_ID="$2"; shift 2 ;;
        --feishu-app-secret) FEISHU_APP_SECRET="$2"; shift 2 ;;
        --feishu-open-id) FEISHU_OPEN_ID="$2"; shift 2 ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

# 1. 检查 Python 版本
echo ""
echo "📋 [1/7] 检查 Python..."
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    echo "   Python 版本: $PY_VER"
else
    echo "   ❌ 未找到 python3，正在安装..."
    if command -v apt-get &>/dev/null; then
        apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip
    elif command -v yum &>/dev/null; then
        yum install -y python3 python3-pip
    elif command -v dnf &>/dev/null; then
        dnf install -y python3 python3-pip
    else
        echo "❌ 无法自动安装 Python，请手动安装 Python >= 3.10"
        exit 1
    fi
fi

# 2. 检查 git
echo ""
echo "📋 [2/7] 检查 git..."
if ! command -v git &>/dev/null; then
    echo "   安装 git..."
    if command -v apt-get &>/dev/null; then
        apt-get install -y -qq git
    elif command -v yum &>/dev/null; then
        yum install -y git
    fi
fi

# 3. 克隆/更新代码
echo ""
echo "📋 [3/7] 部署代码到 $INSTALL_DIR ..."
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "   已存在，拉取最新代码..."
    cd "$INSTALL_DIR"
    git fetch origin
    git reset --hard origin/master
else
    echo "   克隆仓库..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# 4. 创建虚拟环境 + 安装依赖
echo ""
echo "📋 [4/7] 安装 Python 依赖..."
cd "$INSTALL_DIR"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "   ✅ 依赖安装完成"

# 5. 创建必要目录
echo ""
echo "📋 [5/7] 创建目录..."
mkdir -p "$INSTALL_DIR/data"
mkdir -p "$INSTALL_DIR/logs"

# 6. 配置飞书凭据
echo ""
echo "📋 [6/7] 配置飞书通知..."

# 检查 openclaw.json 是否存在
OPENCLAW_DIR="$HOME/.openclaw"
mkdir -p "$OPENCLAW_DIR"

if [ -n "$FEISHU_APP_ID" ] && [ -n "$FEISHU_APP_SECRET" ]; then
    echo "   使用提供的飞书凭据..."
    OPEN_ID="${FEISHU_OPEN_ID:-ou_5f71ffaa82d43a84b54b3a06ed009054}"
    cat > "$OPENCLAW_DIR/openclaw.json" << EOFCONFIG
{
  "channels": {
    "feishu": {
      "domain": "feishu",
      "appId": "$FEISHU_APP_ID",
      "appSecret": "$FEISHU_APP_SECRET",
      "accounts": {
        "stock": {
          "appId": "$FEISHU_APP_ID",
          "appSecret": "$FEISHU_APP_SECRET"
        }
      },
      "openId": "$OPEN_ID"
    }
  }
}
EOF_CONFIG
    echo "   ✅ 飞书凭据已写入 $OPENCLAW_DIR/openclaw.json"
elif [ -f "$OPENCLAW_DIR/openclaw.json" ]; then
    echo "   ✅ 已有 openclaw.json，跳过"
else
    echo "   ⚠️  未提供飞书凭据！通知功能将不可用"
    echo "   请手动创建 $OPENCLAW_DIR/openclaw.json："
    echo '   {"channels":{"feishu":{"appId":"YOUR_APP_ID","appSecret":"YOUR_APP_SECRET","accounts":{"stock":{"appId":"YOUR_APP_ID","appSecret":"YOUR_APP_SECRET"}}}}}'
fi

# 7. 安装 systemd 服务
echo ""
echo "📋 [7/7] 安装 systemd 服务..."
cp "$INSTALL_DIR/deploy/linux/stock-tool.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable stock-tool
systemctl restart stock-tool

echo ""
echo "=========================================="
echo "  ✅ 部署完成！"
echo "=========================================="
echo ""
echo "  管理命令："
echo "    systemctl status stock-tool    # 查看状态"
echo "    systemctl restart stock-tool   # 重启"
echo "    journalctl -u stock-tool -f    # 查看实时日志"
echo "    journalctl -u stock-tool --since today  # 今日日志"
echo ""
echo "  手动运行："
echo "    cd $INSTALL_DIR"
echo "    source venv/bin/activate"
echo "    python3 main.py daemon         # 启动定时任务"
echo "    python3 main.py select run     # 手动选股"
echo "    python3 main.py monitor        # 持仓监控"
echo ""

# 验证服务状态
sleep 3
if systemctl is-active --quiet stock-tool; then
    echo "  🟢 stock-tool 服务运行中"
else
    echo "  🔴 stock-tool 服务未启动，请检查日志："
    echo "     journalctl -u stock-tool -n 50"
fi
