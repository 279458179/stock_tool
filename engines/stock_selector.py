"""盘后选股引擎 — 修复版 2026-05-29"""
import pandas as pd
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging
import time
import baostock as bs

from config import get_config
from data_sources.baostock_api import get_api, BaoStockAPI
from data_sources.tencent_realtime import get_api as get_realtime_api
from strategies.technical import TechnicalStrategy, MACDStrategy, VolumeBreakoutStrategy
from strategies.fundamental import FundamentalStrategy, QualityStockStrategy, LowValuationStrategy
from strategies.base import StrategyManager
from database.operations import CandidateDB

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StockSelector:
    """盘后选股引擎"""

    def __init__(self):
        self.config = get_config()
        self.baostock_api = get_api()
        self.realtime_api = get_realtime_api()
        self.strategy_manager = StrategyManager()
        self.candidate_db = CandidateDB()
        self._register_strategies()

    def _register_strategies(self):
        """注册选股策略"""
        self.strategy_manager.add_strategy(TechnicalStrategy())
        self.strategy_manager.add_strategy(MACDStrategy())
        self.strategy_manager.add_strategy(VolumeBreakoutStrategy())
        self.strategy_manager.add_strategy(FundamentalStrategy())
        self.strategy_manager.add_strategy(QualityStockStrategy())
        self.strategy_manager.add_strategy(LowValuationStrategy())

    def run(self, limit: int = 5) -> List[Dict[str, Any]]:
        """运行选股流程"""
        logger.info("开始选股流程...")

        # 1. 获取股票池
        all_stocks = self._get_stock_pool()
        if not all_stocks:
            logger.error("无法获取股票列表")
            return []
        logger.info(f"获取到{len(all_stocks)}只股票，开始筛选...")

        # 2. 获取所有股票的K线数据（BaoStock串行，但批量获取）
        stock_k_data = self._batch_fetch_k_data(all_stocks)
        logger.info(f"成功获取{len(stock_k_data)}只股票的K线数据")

        # 3. 快速过滤
        filtered_stocks = self._fast_filter_with_data(all_stocks, stock_k_data)
        logger.info(f"快速过滤后剩余{len(filtered_stocks)}只股票")

        # 4. 技术面评分
        scored_stocks = self._score_stocks(filtered_stocks)
        logger.info(f"评分完成，共{len(scored_stocks)}只股票通过")

        # 5. 排序取前N只
        top_stocks = sorted(scored_stocks, key=lambda x: x['total_score'], reverse=True)[:limit]

        # 6. 生成买入建议
        candidates = self._generate_recommendations(top_stocks)

        # 7. 存入数据库
        self._save_candidates(candidates)

        logger.info(f"选股完成，输出{len(candidates)}只候选股")
        return candidates

    def _get_stock_pool(self) -> List[Dict[str, str]]:
        """获取股票池（沪深300成分股）"""
        logger.info("获取沪深300成分股...")
        lg = bs.login()
        if lg.error_code != '0':
            logger.error(f"BaoStock登录失败: {lg.error_msg}")
            return []

        rs = bs.query_hs300_stocks()
        stocks = []
        while rs.next():
            row = rs.get_row_data()
            if len(row) >= 3:
                code = row[1].strip().lower()  # sh.600000
                name = row[2]
                if code.startswith(('sh.', 'sz.')) and len(code) == 9:
                    stocks.append({'code': code, 'name': name})

        bs.logout()
        logger.info(f"沪深300成分股: {len(stocks)} 只")
        return stocks

    def _batch_fetch_k_data(self, stocks: List[Dict[str, str]]) -> Dict[str, Optional[pd.DataFrame]]:
        """批量获取K线数据（BaoStock串行）"""
        max_price = self.config.selector.max_price
        min_price = self.config.selector.min_price
        max_pct = self.config.selector.max_pct_1d

        lg = bs.login()
        if lg.error_code != '0':
            logger.error(f"BaoStock登录失败: {lg.error_msg}")
            return {}

        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')

        results = {}
        total = len(stocks)

        queries_since_login = 0
        for i, stock in enumerate(stocks):
            code = stock['code']
            name = stock.get('name', '')

            # 每40只重新登录一次，避免BaoStock断连
            if queries_since_login >= 40:
                bs.logout()
                time.sleep(0.5)
                lg2 = bs.login()
                if lg2.error_code != '0':
                    logger.error(f"重新登录失败: {lg2.error_msg}")
                    break
                queries_since_login = 0
                logger.info(f"BaoStock重新连接（已处理{i}只）")

            # 过滤ST股
            if 'ST' in name.upper() or 'st' in name:
                continue

            try:
                rs = bs.query_history_k_data_plus(
                    code,
                    'date,code,open,high,low,close,preclose,volume,amount,turn,pctChg',
                    start_date=start_date, end_date=end_date,
                    frequency='d', adjustflag='2'  # 前复权
                )

                if rs.error_code != '0':
                    continue

                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())

                if not rows:
                    continue

                df = pd.DataFrame(rows, columns=rs.fields)
                numeric_cols = ['open', 'high', 'low', 'close', 'preclose', 'volume', 'amount', 'turn', 'pctChg']
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                last_close = float(df['close'].iloc[-1])

                # 快速价格过滤
                if last_close < min_price or last_close > max_price:
                    continue

                # 1日涨幅过滤（追高过滤）
                if len(df) >= 2:
                    prev_close = float(df['close'].iloc[-2])
                    if prev_close > 0:
                        pct_1d = (last_close - prev_close) / prev_close * 100
                        if pct_1d > max_pct:
                            continue

                # 成交量过滤
                if len(df) >= 5:
                    avg_volume = df['volume'].iloc[-5:].mean()
                    if avg_volume < 1000:
                        continue

                results[code] = {
                    'df': df,
                    'name': name,
                    'last_close': last_close,
                }

            except Exception as e:
                logger.warning(f"获取{code}数据失败: {e}")

            # 每50只打印进度
            if (i + 1) % 50 == 0:
                logger.info(f"已处理 {i+1}/{total}")

            queries_since_login += 1

        bs.logout()
        return results

    def _fast_filter_with_data(self, stocks: List[Dict[str, str]], k_data: Dict[str, dict]) -> List[Dict[str, Any]]:
        """快速过滤"""
        filtered = []
        for stock in stocks:
            code = stock['code']
            if code in k_data:
                data = k_data[code]
                filtered.append({
                    'code': code,
                    'name': data['name'],
                    'k_data': data['df'],
                    'last_close': data['last_close'],
                })
        return filtered

    def _score_stocks(self, filtered_stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """技术面+基本面综合评分"""
        scored = []

        for stock in filtered_stocks:
            result = self._score_single(stock)
            if result and result.get('passed'):
                scored.append(result)

        return scored

    def _score_single(self, stock: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """单只股票评分"""
        try:
            code = stock['code']
            name = stock['name']
            df = stock['k_data']
            last_close = stock['last_close']

            if df.empty or len(df) < 20:
                return None

            # 技术面信号计数
            signal_count = 0
            signals = []

            # 1. 均线排列检测
            ma5 = df['close'].rolling(5).mean().iloc[-1]
            ma10 = df['close'].rolling(10).mean().iloc[-1]
            ma20 = df['close'].rolling(20).mean().iloc[-1]

            if ma5 > ma10 > ma20:
                signal_count += 1
                signals.append("短期均线向上")

            # 2. 趋势检测（20日涨幅）
            close_20 = df['close'].iloc[-20]
            if close_20 > 0:
                pct_20 = (last_close - close_20) / close_20 * 100
                if pct_20 > 2:
                    signal_count += 1
                    signals.append(f"20日涨{pct_20:.1f}%趋势向上")

            # 3. MACD检测
            exp12 = df['close'].ewm(span=12, adjust=False).mean()
            exp26 = df['close'].ewm(span=26, adjust=False).mean()
            dif = exp12 - exp26
            dea = dif.ewm(span=9, adjust=False).mean()

            if dif.iloc[-1] > dea.iloc[-1]:
                signal_count += 1
                signals.append("MACD看多")

            # 4. 量价配合
            vol_5 = df['volume'].iloc[-5:].mean()
            vol_20 = df['volume'].iloc[-20:].mean()
            if vol_20 > 0 and vol_5 > vol_20 * 0.8:
                signal_count += 1
                signals.append("量能正常")

            # 5. 突破信号（接近20日高点）
            high_20 = df['high'].iloc[-20:].max()
            if last_close >= high_20 * 0.97:
                signal_count += 1
                signals.append("接近/突破20日高点")

            # 综合评分（信号数 × 20分，最高100分）
            score = min(signal_count * 20, 100)

            # 判断是否通过
            passed = (score >= self.config.selector.min_score and
                      signal_count >= self.config.selector.min_signals)

            if not passed:
                return None

            return {
                'code': code,
                'name': name,
                'total_score': score,
                'signal_count': signal_count,
                'signals': signals,
                'passed': True,
                'last_close': last_close,
                'pct_1d': self._calc_pct(df, 1),
                'pct_5d': self._calc_pct(df, 5),
                'pct_20d': self._calc_pct(df, 20),
                'volume_ratio': vol_5 / vol_20 if vol_20 > 0 else 1.0,
            }
        except Exception as e:
            logger.error(f"评分{stock.get('code', '?')}失败: {e}")
            return None

    def _calc_pct(self, df: pd.DataFrame, days: int) -> float:
        """计算N日涨幅"""
        if len(df) < days + 1:
            return 0.0
        close_n = df['close'].iloc[-(days + 1)]
        close_now = df['close'].iloc[-1]
        if close_n <= 0:
            return 0.0
        return (close_now - close_n) / close_n * 100

    def _generate_recommendations(self, scored_stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """生成买入建议"""
        candidates = []

        for stock in scored_stocks:
            last_close = stock['last_close']
            score = stock['total_score']

            # 支撑位 = 5日均线附近
            support = last_close * 0.98

            # 买入区间
            buy_range_low = last_close * 0.97  # -3%（激进）
            buy_range_high = last_close * 0.99  # -1%

            # 止损 = 支撑位下方5%
            stop_loss = support * 0.95

            # 目标价 = 现价 + 8%~15%（根据评分）
            target_up = 0.08 + min(score / 100, 1.0) * 0.07  # 8%~15%
            target_price = last_close * (1 + target_up)

            # 仓位建议
            if score >= 80:
                position_advice = "建议仓位：可配置总资金的20%-30%"
            elif score >= 60:
                position_advice = "建议仓位：可配置总资金的10%-20%"
            else:
                position_advice = "建议仓位：可配置总资金的5%-10%"

            # 选入理由
            reason = "；".join(stock.get('signals', [])[:5]) or "综合评分达标"

            candidate = {
                'code': stock['code'].replace('sh.', '').replace('sz.', ''),
                'name': stock['name'],
                'score': score,
                'signal_count': stock['signal_count'],
                'buy_range_low': buy_range_low,
                'buy_range_high': buy_range_high,
                'target_price': target_price,
                'stop_loss': stop_loss,
                'position_advice': position_advice,
                'reason': reason,
                'last_close': last_close,
                'pct_1d': stock.get('pct_1d', 0),
                'pct_5d': stock.get('pct_5d', 0),
                'pct_20d': stock.get('pct_20d', 0),
                'volume_ratio': stock.get('volume_ratio', 1.0),
            }

            candidates.append(candidate)

        return candidates

    def _save_candidates(self, candidates: List[Dict[str, Any]]):
        """保存候选股到数据库"""
        today = datetime.now().strftime("%Y-%m-%d")

        for candidate in candidates:
            self.candidate_db.add_candidate(
                code=candidate['code'],
                name=candidate['name'],
                select_date=today,
                buy_range_low=candidate['buy_range_low'],
                buy_range_high=candidate['buy_range_high'],
                target_price=candidate['target_price'],
                stop_loss=candidate['stop_loss'],
                position_advice=candidate['position_advice'],
                reason=candidate['reason'],
                score=candidate['score']
            )
