"""腾讯实时行情接口"""
import requests
import re
import json
from typing import List, Dict, Optional, Any
from datetime import datetime
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TencentRealtimeAPI:
    """腾讯实时行情API封装"""

    # 腾讯股票查询接口
    QUOTE_URL = "https://qt.gtimg.cn/q="
    # 腾讯财经API
    FINANCE_URL = "https://web.sqt.gtimg.cn/q="

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://gu.qq.com/'
        })

    def _format_code(self, code: str) -> str:
        """
        格式化股票代码为腾讯格式

        Args:
            code: 原始代码，如600519或sh600519

        Returns:
            腾讯格式代码，如sh600519
        """
        # 去除可能的前缀
        code = code.replace('sh.', '').replace('sz.', '').replace('SH', '').replace('SZ', '')

        # 根据代码判断市场
        if code.startswith('6'):
            return f'sh{code}'
        else:
            return f'sz{code}'

    def get_realtime_quote(self, code: str) -> Dict[str, Any]:
        """
        获取单只股票实时行情

        Args:
            code: 股票代码

        Returns:
            行情数据字典
        """
        formatted_code = self._format_code(code)
        url = f"{self.QUOTE_URL}{formatted_code}"

        try:
            response = self.session.get(url, timeout=5)
            response.raise_for_status()
            content = response.text

            # 解析腾讯返回的数据格式 v_sh600519="1~茅台~600519~..."
            pattern = r'v_([^=]+)="([^"]+)"'
            match = re.search(pattern, content)

            if not match:
                logger.warning(f"未找到股票数据: {code}")
                return {}

            stock_code = match.group(1)
            data_str = match.group(2)

            # 分割数据
            parts = data_str.split('~')

            if len(parts) < 30:
                return {}

            quote = {
                'code': code,
                'tencent_code': stock_code,
                'name': parts[1] if len(parts) > 1 else '',
                'price': float(parts[3]) if parts[3] else 0,
                'last_close': float(parts[4]) if parts[4] else 0,
                'open': float(parts[5]) if parts[5] else 0,
                'volume': float(parts[6]) if parts[6] else 0,
                'amount': float(parts[36]) if len(parts) > 36 and parts[36] else 0,
                'bid1': float(parts[9]) if len(parts) > 9 and parts[9] else 0,
                'ask1': float(parts[19]) if len(parts) > 19 and parts[19] else 0,
                'high': float(parts[33]) if len(parts) > 33 and parts[33] else 0,
                'low': float(parts[34]) if len(parts) > 34 and parts[34] else 0,
                'change_pct': float(parts[32]) if len(parts) > 32 and parts[32] else 0,
                'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

            # 计算涨跌额
            quote['change'] = quote['price'] - quote['last_close']

            return quote

        except requests.RequestException as e:
            logger.error(f"请求失败: {e}")
            return {}

    def get_batch_quotes(self, codes: List[str]) -> List[Dict[str, Any]]:
        """
        批量获取实时行情

        Args:
            codes: 股票代码列表

        Returns:
            行情数据列表
        """
        if not codes:
            return []

        # 格式化代码
        formatted_codes = [self._format_code(c) for c in codes]
        url = f"{self.QUOTE_URL}{','.join(formatted_codes)}"

        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            content = response.text

            quotes = []
            pattern = r'v_([^=]+)="([^"]+)"'

            for match in re.finditer(pattern, content):
                stock_code = match.group(1)
                data_str = match.group(2)
                parts = data_str.split('~')

                if len(parts) < 30:
                    continue

                # 转换回原始代码格式
                original_code = stock_code.replace('sh', '').replace('sz', '')

                quote = {
                    'code': original_code,
                    'tencent_code': stock_code,
                    'name': parts[1] if len(parts) > 1 else '',
                    'price': float(parts[3]) if parts[3] else 0,
                    'last_close': float(parts[4]) if parts[4] else 0,
                    'open': float(parts[5]) if parts[5] else 0,
                    'volume': float(parts[6]) if parts[6] else 0,
                    'amount': float(parts[36]) if len(parts) > 36 and parts[36] else 0,
                    'high': float(parts[33]) if len(parts) > 33 and parts[33] else 0,
                    'low': float(parts[34]) if len(parts) > 34 and parts[34] else 0,
                    'change_pct': float(parts[32]) if len(parts) > 32 and parts[32] else 0,
                    'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }

                quote['change'] = quote['price'] - quote['last_close']
                quotes.append(quote)

            return quotes

        except requests.RequestException as e:
            logger.error(f"批量请求失败: {e}")
            return []

    def get_auction_data(self, code: str) -> Dict[str, Any]:
        """
        获取集合竞价数据

        Args:
            code: 股票代码

        Returns:
            竞价数据
        """
        quote = self.get_realtime_quote(code)

        if not quote:
            return {}

        # 竞价期间，开盘价可能为0，需要特殊处理
        auction_price = quote['open'] if quote['open'] > 0 else quote['price']
        auction_volume = quote['volume']

        return {
            'code': code,
            'name': quote['name'],
            'auction_price': auction_price,
            'last_close': quote['last_close'],
            'auction_change_pct': (auction_price - quote['last_close']) / quote['last_close'] * 100 if quote['last_close'] > 0 else 0,
            'auction_volume': auction_volume,
            'time': quote['time'],
        }

    def get_batch_auction_data(self, codes: List[str]) -> List[Dict[str, Any]]:
        """批量获取竞价数据"""
        quotes = self.get_batch_quotes(codes)

        auction_data = []
        for quote in quotes:
            auction_price = quote['open'] if quote['open'] > 0 else quote['price']
            auction_data.append({
                'code': quote['code'],
                'name': quote['name'],
                'auction_price': auction_price,
                'last_close': quote['last_close'],
                'auction_change_pct': (auction_price - quote['last_close']) / quote['last_close'] * 100 if quote['last_close'] > 0 else 0,
                'auction_volume': quote['volume'],
                'time': quote['time'],
            })

        return auction_data

    def get_market_status(self) -> str:
        """
        获取市场状态

        Returns:
            trading/pre_market/auction/closed
        """
        now = datetime.now()

        # 周末直接返回closed（周六=5，周日=6）
        if now.weekday() >= 5:
            return "closed"

        current_time = now.strftime("%H:%M")

        # A股交易时间（仅工作日）
        # 09:15-09:25 集合竞价
        # 09:30-11:30 上午交易
        # 13:00-15:00 下午交易

        if current_time >= "09:15" and current_time < "09:25":
            return "auction"
        elif current_time >= "09:30" and current_time < "11:30":
            return "trading"
        elif current_time >= "13:00" and current_time < "15:00":
            return "trading"
        elif current_time >= "09:25" and current_time < "09:30":
            return "pre_market"
        else:
            return "closed"

    def is_trading_time(self) -> bool:
        """是否交易时间"""
        return self.get_market_status() == "trading"

    def is_auction_time(self) -> bool:
        """是否竞价时间"""
        return self.get_market_status() == "auction"

    def get_realtime_quotes_loop(
        self,
        codes: List[str],
        interval: float = 1.0,
        max_loops: int = 0
    ) -> List[Dict[str, Any]]:
        """
        循环获取实时行情（用于监控）

        Args:
            codes: 股票代码列表
            interval: 刷新间隔（秒）
            max_loops: 最大循环次数，0表示无限

        Returns:
            最后一次获取的行情数据
        """
        loop_count = 0

        while True:
            quotes = self.get_batch_quotes(codes)
            yield quotes

            loop_count += 1
            if max_loops > 0 and loop_count >= max_loops:
                break

            time.sleep(interval)


class RealtimeQuoteMonitor:
    """实时行情监控器"""

    def __init__(self, codes: List[str]):
        self.api = TencentRealtimeAPI()
        self.codes = codes
        self._running = False

    def start(self, callback: callable, interval: float = 1.0):
        """
        启动监控

        Args:
            callback: 每次获取数据后的回调函数
            interval: 刷新间隔
        """
        self._running = True

        while self._running:
            # 只在交易时间获取数据
            if self.api.is_trading_time() or self.api.is_auction_time():
                quotes = self.api.get_batch_quotes(self.codes)
                callback(quotes)

            time.sleep(interval)

    def stop(self):
        """停止监控"""
        self._running = False


# 全局实例
_api_instance: Optional[TencentRealtimeAPI] = None


def get_api() -> TencentRealtimeAPI:
    """获取全局API实例"""
    global _api_instance
    if _api_instance is None:
        _api_instance = TencentRealtimeAPI()
    return _api_instance