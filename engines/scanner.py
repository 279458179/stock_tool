"""盘中异动扫描模块"""
from typing import List, Dict, Any
from datetime import datetime
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import get_config
from data_sources.baostock_api import get_api, BaoStockAPI
from data_sources.tencent_realtime import get_api as get_realtime_api, TencentRealtimeAPI
from notifications.notifier import Notifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Scanner:
    """盘中异动扫描器"""

    def __init__(self):
        self.config = get_config()
        self.baostock_api = get_api()
        self.realtime_api = get_realtime_api()
        self.notifier = Notifier()

    def scan(self, min_score: int = 70) -> List[Dict[str, Any]]:
        """
        执行异动扫描

        Args:
            min_score: 最低评分，低于此分数的不会推送

        Returns:
            异动股票列表
        """
        logger.info("开始盘中异动扫描...")

        # 获取股票池
        stocks = self._get_scan_pool()

        if not stocks:
            logger.warning("股票池为空")
            return []

        results = []

        # 并行扫描
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(self._scan_single_stock, stock): stock for stock in stocks}

            for future in as_completed(futures):
                stock = futures[future]
                try:
                    result = future.result()
                    if result and result['score'] >= min_score:
                        results.append(result)
                except Exception as e:
                    logger.warning(f"扫描{stock}时出错: {e}")

        # 按评分排序
        results.sort(key=lambda x: x['score'], reverse=True)

        logger.info(f"扫描完成，发现{len(results)}只异动股票")

        # 发送通知
        if results:
            self._send_scan_notification(results)

        return results

    def _get_scan_pool(self) -> List[str]:
        """获取扫描池"""
        # 可以扫描全市场，或者只扫描关注列表
        # 这里限制数量以提高效率
        stocks = self.baostock_api.get_stock_codes()
        return stocks[:200]  # 扫描前200只

    def _scan_single_stock(self, code: str) -> Dict[str, Any]:
        """扫描单只股票"""
        try:
            # 获取实时行情
            quote = self.realtime_api.get_realtime_quote(code)

            if not quote or quote.get('price', 0) == 0:
                return None

            # 获取历史K线
            k_data = self.baostock_api.get_recent_k_data(
                f"sh.{code}" if code.startswith('6') else f"sz.{code}",
                days=20
            )

            if k_data.empty:
                return None

            # 检测异动类型
            anomalies = self._detect_anomalies(quote, k_data)

            if not anomalies:
                return None

            # 计算评分
            score = self._calculate_anomaly_score(anomalies)

            return {
                'code': code,
                'name': quote.get('name', ''),
                'price': quote.get('price', 0),
                'change_pct': quote.get('change_pct', 0),
                'volume': quote.get('volume', 0),
                'anomalies': anomalies,
                'score': score,
                'type': anomalies[0]['type'] if anomalies else 'unknown',
                'detail': anomalies[0]['detail'] if anomalies else ''
            }

        except Exception as e:
            logger.error(f"扫描{code}失败: {e}")
            return None

    def _detect_anomalies(self, quote: Dict[str, Any], k_data: Any) -> List[Dict[str, Any]]:
        """检测异动类型"""
        anomalies = []

        current_price = quote.get('price', 0)
        current_volume = quote.get('volume', 0)
        change_pct = quote.get('change_pct', 0)

        # 1. 放量突破检测
        avg_volume = k_data['volume'].iloc[-5:].mean()
        if current_volume > 0 and avg_volume > 0:
            volume_ratio = current_volume / avg_volume
            if volume_ratio >= 2:
                # 判断是否突破前高
                recent_high = k_data['high'].iloc[-10:].max()
                if current_price > recent_high:
                    anomalies.append({
                        'type': '放量突破',
                        'detail': f'量比{volume_ratio:.1f}倍，突破{recent_high:.2f}',
                        'score': 90
                    })
                elif volume_ratio >= 3:
                    anomalies.append({
                        'type': '大幅放量',
                        'detail': f'量比{volume_ratio:.1f}倍',
                        'score': 70
                    })

        # 2. 均线金叉检测
        ma5 = k_data['close'].rolling(window=5).mean().iloc[-1]
        ma10 = k_data['close'].rolling(window=10).mean().iloc[-1]
        ma5_prev = k_data['close'].rolling(window=5).mean().iloc[-2]
        ma10_prev = k_data['close'].rolling(window=10).mean().iloc[-2]

        if ma5 > ma10 and ma5_prev <= ma10_prev:
            anomalies.append({
                'type': '均线金叉',
                'detail': 'MA5上穿MA10',
                'score': 80
            })

        # 3. 大单异动检测（估算）
        # 根据成交额和平均成交额估算
        avg_amount = k_data['volume'].iloc[-5:].mean() * k_data['close'].iloc[-5:].mean()
        current_amount = quote.get('amount', 0)

        if current_amount > avg_amount * 2:
            # 假设大单流入
            if change_pct > 0:
                anomalies.append({
                    'type': '大单流入',
                    'detail': f'成交额异常放大',
                    'score': 75
                })

        # 4. 涨幅异动检测
        if change_pct >= 5:
            anomalies.append({
                'type': '大幅上涨',
                'detail': f'涨幅{change_pct:.1f}%',
                'score': 85
            })
        elif change_pct >= 3:
            anomalies.append({
                'type': '强势上涨',
                'detail': f'涨幅{change_pct:.1f}%',
                'score': 60
            })

        # 5. 价格站上均线检测
        ma20 = k_data['close'].rolling(window=20).mean().iloc[-1] if len(k_data) >= 20 else 0
        ma60 = k_data['close'].rolling(window=60).mean().iloc[-1] if len(k_data) >= 60 else 0

        above_count = 0
        if current_price > ma5:
            above_count += 1
        if current_price > ma10:
            above_count += 1
        if current_price > ma20:
            above_count += 1
        if current_price > ma60:
            above_count += 1

        if above_count >= 3 and change_pct > 0:
            anomalies.append({
                'type': '均线多头',
                'detail': f'站上{above_count}条均线',
                'score': 65
            })

        return anomalies

    def _calculate_anomaly_score(self, anomalies: List[Dict[str, Any]]) -> int:
        """计算异动评分"""
        if not anomalies:
            return 0

        # 取最高分的异动作为主评分
        max_score = max(a['score'] for a in anomalies)

        # 其他异动加分
        bonus = sum(a['score'] * 0.1 for a in anomalies if a['score'] < max_score)

        return int(max_score + bonus)

    def _send_scan_notification(self, results: List[Dict[str, Any]]):
        """发送扫描通知"""
        top_results = results[:5]  # 只推送前5个

        message_lines = ["发现异动股票："]
        for r in top_results:
            message_lines.append(
                f"{r['name']}({r['code']}): {r['type']} 评分{r['score']} 现价{r['price']:.2f}"
            )

        self.notifier.send_alert(
            title="盘中异动扫描",
            message="\n".join(message_lines),
            level="info"
        )

    def scan_by_type(self, anomaly_type: str) -> List[Dict[str, Any]]:
        """按异动类型扫描"""
        results = self.scan()

        return [r for r in results if r['type'] == anomaly_type]

    def scan_volume_breakout(self) -> List[Dict[str, Any]]:
        """放量突破扫描"""
        return self.scan_by_type('放量突破')

    def scan_ma_golden_cross(self) -> List[Dict[str, Any]]:
        """均线金叉扫描"""
        return self.scan_by_type('均线金叉')


class AnomalyDetector:
    """异动检测器"""

    def detect_volume_anomaly(self, quote: Dict[str, Any], k_data: Any) -> bool:
        """检测成交量异动"""
        current_volume = quote.get('volume', 0)
        avg_volume = k_data['volume'].iloc[-5:].mean()

        if avg_volume <= 0:
            return False

        volume_ratio = current_volume / avg_volume

        # 量比超过2倍视为异动
        return volume_ratio >= 2

    def detect_price_anomaly(self, quote: Dict[str, Any], k_data: Any) -> bool:
        """检测价格异动"""
        change_pct = quote.get('change_pct', 0)

        # 涨幅超过3%视为异动
        return abs(change_pct) >= 3

    def detect_trend_anomaly(self, quote: Dict[str, Any], k_data: Any) -> bool:
        """检测趋势异动"""
        if len(k_data) < 10:
            return False

        ma5 = k_data['close'].rolling(window=5).mean()
        ma10 = k_data['close'].rolling(window=10).mean()

        # MA5上穿MA10视为趋势异动
        if ma5.iloc[-1] > ma10.iloc[-1] and ma5.iloc[-2] <= ma10.iloc[-2]:
            return True

        return False