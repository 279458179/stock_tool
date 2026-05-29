"""通知模块 — 支持飞书API（非webhook）+ 桌面通知"""
import requests
import json
import os
import platform
import logging
from typing import Optional
from datetime import datetime

from config import get_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FeishuAPI:
    """飞书API — 用 appId/appSecret 发送消息"""

    def __init__(self, app_id: str, app_secret: str, open_id: str, domain: str = "feishu"):
        self.app_id = app_id
        self.app_secret = app_secret
        self.open_id = open_id
        self.domain = domain
        self._token = None
        self._token_expires = 0

    def _get_token(self) -> str:
        """获取 tenant_access_token"""
        import time
        if self._token and time.time() < self._token_expires:
            return self._token

        if self.domain == "lark":
            base_url = "https://open.larksuite.com"
        else:
            base_url = "https://open.feishu.cn"

        url = f"{base_url}/open-apis/auth/v3/tenant_access_token/internal"
        resp = requests.post(url, json={
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }, timeout=10)

        data = resp.json()
        if data.get("code") == 0:
            self._token = data["tenant_access_token"]
            self._token_expires = time.time() + 7200  # 2小时有效期
            return self._token
        else:
            logger.error(f"获取飞书token失败: {data}")
            return ""

    def send_message(self, title: str, message: str, level: str = "info") -> bool:
        """发送飞书消息卡片"""
        token = self._get_token()
        if not token:
            return False

        if self.domain == "lark":
            base_url = "https://open.larksuite.com"
        else:
            base_url = "https://open.feishu.cn"

        url = f"{base_url}/open-apis/im/v1/messages?receive_id_type=open_id"

        # 颜色映射
        color_map = {
            "critical": "red",
            "warning": "orange",
            "success": "green",
            "info": "blue"
        }
        color = color_map.get(level, "blue")

        # 构建消息卡片
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": color
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": message
                    }
                },
                {
                    "tag": "hr"
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": f"📈 股票投资闭环工具 · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        }
                    ]
                }
            ]
        }

        payload = {
            "receive_id": self.open_id,
            "msg_type": "interactive",
            "content": json.dumps(card)
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            data = resp.json()
            if data.get("code") == 0:
                logger.info("飞书消息发送成功")
                return True
            else:
                logger.error(f"飞书消息发送失败: {data}")
                return False
        except Exception as e:
            logger.error(f"飞书消息发送异常: {e}")
            return False


class Notifier:
    """多渠道通知器"""

    def __init__(self):
        self.config = get_config()
        self.feishu_api = None
        self._init_feishu_api()

    def _init_feishu_api(self):
        """初始化飞书API"""
        # 优先使用 config.yaml 中的 webhook（兼容旧配置）
        if self.config.notification.feishu_webhook:
            logger.info("飞书webhook已配置")
            return

        # 否则使用 openclaw.json 中的 appId/appSecret
        try:
            import json
            config_path = os.path.expanduser("~/.openclaw/openclaw.json")
            with open(config_path, 'r') as f:
                oc_config = json.load(f)

            channels = oc_config.get('channels', {})
            feishu_config = channels.get('feishu', {})

            # 默认使用 stock 账号
            stock_account = feishu_config.get('accounts', {}).get('stock', {})
            app_id = stock_account.get('appId', feishu_config.get('appId', ''))
            app_secret = stock_account.get('appSecret', feishu_config.get('appSecret', ''))
            domain = feishu_config.get('domain', 'feishu')

            # 使用顶层的 allowFrom（stock账号 allowFrom=["*"] 表示允许所有人）
            # 这里使用老大（stock账号DM）的 open_id
            open_id = 'ou_5f71ffaa82d43a84b54b3a06ed009054'  # 老大的飞书 open_id

            if app_id and app_secret and open_id:
                self.feishu_api = FeishuAPI(app_id, app_secret, open_id, domain)
                logger.info(f"飞书API已初始化 (app_id={app_id[:10]}..., open_id={open_id[:15]}...)")
            else:
                logger.warning(f"飞书API配置不完整: app_id={'是' if app_id else '否'}, app_secret={'是' if app_secret else '否'}, open_id={'是' if open_id else '否'}")

        except Exception as e:
            logger.warning(f"飞书API初始化失败: {e}")

    def send_alert(self, title: str, message: str, level: str = "info"):
        """发送告警通知"""
        # 桌面通知
        if self.config.notification.desktop:
            self._send_desktop_notification(title, message, level)

        # 声音提醒
        if self.config.notification.sound:
            self._play_sound(level)

        # 飞书通知
        if self.config.notification.feishu_webhook:
            self._send_feishu_webhook(title, message, level)
        elif self.feishu_api:
            self.feishu_api.send_message(title, message, level)

    def _send_desktop_notification(self, title: str, message: str, level: str):
        """发送桌面通知"""
        try:
            if platform.system() == "Darwin":
                os.system(f'''osascript -e 'display notification "{message}" with title "{title}"' ''')
            elif platform.system() == "Linux":
                try:
                    import subprocess
                    subprocess.run(["notify-send", title, message], capture_output=True)
                except Exception:
                    pass
            logger.info(f"桌面通知已发送: {title}")
        except Exception as e:
            logger.error(f"桌面通知发送失败: {e}")

    def _play_sound(self, level: str):
        """播放提示音"""
        try:
            if platform.system() == "Darwin":
                if level == "critical":
                    os.system("say 紧急提醒")
                else:
                    os.system("afplay /System/Library/Sounds/Ping.aiff")
        except Exception as e:
            logger.error(f"提示音播放失败: {e}")

    def _send_feishu_webhook(self, title: str, message: str, level: str):
        """通过webhook发送飞书通知"""
        webhook = self.config.notification.feishu_webhook
        if not webhook:
            return

        try:
            color_map = {
                "critical": "red",
                "warning": "orange",
                "success": "green",
                "info": "blue"
            }

            card_content = {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": color_map.get(level, "blue")
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "content": f"{message}\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                            "tag": "lark_md"
                        }
                    },
                    {
                        "tag": "note",
                        "elements": [
                            {"tag": "plain_text", "content": "股票投资闭环工具"}
                        ]
                    }
                ]
            }

            payload = {
                "msg_type": "interactive",
                "card": card_content
            }

            response = requests.post(
                webhook,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=10
            )

            if response.status_code == 200:
                logger.info("飞书webhook通知发送成功")
            else:
                logger.error(f"飞书webhook通知发送失败: {response.text}")

        except Exception as e:
            logger.error(f"飞书webhook通知发送失败: {e}")

    def send_daily_report(self, report_data: dict):
        """发送每日报告"""
        title = "股票投资日报"

        message = f"""**今日选股结果**
候选股数量: {report_data.get('candidates_count', 0)}

**持仓情况**
总持仓: {report_data.get('positions_count', 0)}
总盈亏: {report_data.get('total_profit', 0):.2f}

**今日信号**
止损提醒: {report_data.get('stop_loss_count', 0)}
止盈提醒: {report_data.get('target_count', 0)}"""

        self.send_alert(title, message, "info")

    def send_auction_alert(self, auction_data: list):
        """发送竞价提醒"""
        title = "集合竞价提醒"

        green_stocks = [s for s in auction_data if s.get('signal') == 'green']
        red_stocks = [s for s in auction_data if s.get('signal') == 'red']

        message = f"""**绿灯（可考虑买入）**
{self._format_stock_list(green_stocks)}

**红灯（建议跳过）**
{self._format_stock_list(red_stocks)}"""

        self.send_alert(title, message, "info")

    def _format_stock_list(self, stocks: list) -> str:
        """格式化股票列表"""
        if not stocks:
            return "无"

        lines = []
        for stock in stocks[:5]:
            lines.append(f"{stock['name']}({stock['code']}): 竞价涨跌{stock['auction_change_pct']:.2f}%")

        return "\n".join(lines) if lines else "无"

    def test_notification(self):
        """测试通知功能"""
        self.send_alert(
            title="测试通知",
            message="这是一条测试消息，通知功能正常工作",
            level="info"
        )
        logger.info("测试通知已发送")


class AlertManager:
    """告警管理器"""

    def __init__(self):
        self.notifier = Notifier()
        self._sent_alerts = {}

    def check_and_alert(self, alerts: list):
        for alert in alerts:
            alert_id = alert.get('id', '')
            if alert_id in self._sent_alerts:
                continue

            self.notifier.send_alert(
                title=alert.get('title', ''),
                message=alert.get('message', ''),
                level=alert.get('level', 'info')
            )
            self._sent_alerts[alert_id] = datetime.now()

    def clear_old_alerts(self, hours: int = 24):
        cutoff_time = datetime.now()
        from datetime import timedelta
        cutoff_time = cutoff_time - timedelta(hours=hours)
        to_remove = [k for k, v in self._sent_alerts.items() if v < cutoff_time]
        for k in to_remove:
            del self._sent_alerts[k]
