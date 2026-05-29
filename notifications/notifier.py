"""通知模块"""
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


class Notifier:
    """多渠道通知器"""

    def __init__(self):
        self.config = get_config()

    def send_alert(self, title: str, message: str, level: str = "info"):
        """
        发送告警通知

        Args:
            title: 标题
            message: 内容
            level: 级别 info/warning/critical/success
        """
        # 桌面通知
        if self.config.notification.desktop:
            self._send_desktop_notification(title, message, level)

        # 声音提醒
        if self.config.notification.sound:
            self._play_sound(level)

        # 飞书通知
        if self.config.notification.feishu_webhook:
            self._send_feishu_notification(title, message, level)

    def _send_desktop_notification(self, title: str, message: str, level: str):
        """发送桌面通知"""
        try:
            if platform.system() == "Windows":
                # Windows使用win10toast或plyer
                try:
                    from plyer import notification
                    notification.notify(
                        title=title,
                        message=message,
                        app_name="股票监控工具",
                        timeout=10
                    )
                except ImportError:
                    # 备用方案：使用PowerShell
                    import subprocess
                    ps_script = f'''
                    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
                    $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
                    $textNodes = $template.GetElementsByTagName('text')
                    $textNodes.Item(0).InnerText = "{title}"
                    $textNodes.Item(1).InnerText = "{message}"
                    $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
                    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Stock Tool").Show($toast)
                    '''
                    subprocess.run(["powershell", "-Command", ps_script], capture_output=True)

            elif platform.system() == "Darwin":  # macOS
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
            # 根据级别选择不同的声音
            if platform.system() == "Windows":
                if level == "critical":
                    # 紧急情况使用系统警告音
                    import winsound
                    winsound.Beep(1000, 500)
                    winsound.Beep(1000, 500)
                elif level == "warning":
                    import winsound
                    winsound.Beep(800, 300)
                elif level == "success":
                    import winsound
                    winsound.Beep(500, 200)
                else:
                    import winsound
                    winsound.MessageBeep()

            elif platform.system() == "Darwin":
                if level == "critical":
                    os.system("say 紧急提醒")
                else:
                    os.system("afplay /System/Library/Sounds/Ping.aiff")

            elif platform.system() == "Linux":
                os.system("paplay /usr/share/sounds/freedesktop/stereo/message.oga")

            logger.info(f"提示音已播放: {level}")

        except Exception as e:
            logger.error(f"提示音播放失败: {e}")

    def _send_feishu_notification(self, title: str, message: str, level: str):
        """发送飞书通知"""
        webhook = self.config.notification.feishu_webhook

        if not webhook:
            return

        try:
            # 飞书消息卡片格式
            color_map = {
                "critical": "red",
                "warning": "orange",
                "success": "green",
                "info": "blue"
            }

            card_content = {
                "config": {
                    "wide_screen_mode": True
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "content": f"**{title}**\n{message}\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                            "tag": "lark_md"
                        }
                    },
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": "股票投资闭环工具"
                            }
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
                logger.info("飞书通知已发送")
            else:
                logger.error(f"飞书通知发送失败: {response.text}")

        except Exception as e:
            logger.error(f"飞书通知发送失败: {e}")

    def send_daily_report(self, report_data: dict):
        """发送每日报告"""
        title = "股票投资日报"

        message = f"""
**今日选股结果**
候选股数量: {report_data.get('candidates_count', 0)}

**持仓情况**
总持仓: {report_data.get('positions_count', 0)}
总盈亏: {report_data.get('total_profit', 0):.2f}

**今日信号**
止损提醒: {report_data.get('stop_loss_count', 0)}
止盈提醒: {report_data.get('target_count', 0)}
"""

        self.send_alert(title, message, "info")

    def send_auction_alert(self, auction_data: list):
        """发送竞价提醒"""
        title = "集合竞价提醒"

        green_stocks = [s for s in auction_data if s.get('signal') == 'green']
        red_stocks = [s for s in auction_data if s.get('signal') == 'red']

        message = f"""
**绿灯（可考虑买入）**
{self._format_stock_list(green_stocks)}

**红灯（建议跳过）**
{self._format_stock_list(red_stocks)}
"""

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
        self._sent_alerts = {}  # 已发送的告警记录

    def check_and_alert(self, alerts: list):
        """
        检查并发送告警

        Args:
            alerts: 告警列表
        """
        for alert in alerts:
            alert_id = alert.get('id', '')

            # 避免重复发送
            if alert_id in self._sent_alerts:
                continue

            self.notifier.send_alert(
                title=alert.get('title', ''),
                message=alert.get('message', ''),
                level=alert.get('level', 'info')
            )

            self._sent_alerts[alert_id] = datetime.now()

    def clear_old_alerts(self, hours: int = 24):
        """清理旧告警记录"""
        cutoff_time = datetime.now() - datetime.timedelta(hours=hours)

        to_remove = []
        for alert_id, sent_time in self._sent_alerts.items():
            if sent_time < cutoff_time:
                to_remove.append(alert_id)

        for alert_id in to_remove:
            del self._sent_alerts[alert_id]