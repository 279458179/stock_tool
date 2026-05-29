"""盘后选股引擎"""
import pandas as pd
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

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

        # 注册策略
        self._register_strategies()

    def _register_strategies(self):
        """注册选股策略"""
        # 技术面策略
        self.strategy_manager.add_strategy(TechnicalStrategy())
        self.strategy_manager.add_strategy(MACDStrategy())
        self.strategy_manager.add_strategy(VolumeBreakoutStrategy())

        # 基本面策略
        self.strategy_manager.add_strategy(FundamentalStrategy())
        self.strategy_manager.add_strategy(QualityStockStrategy())
        self.strategy_manager.add_strategy(LowValuationStrategy())

    def run(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        运行选股流程

        Args:
            limit: 输出候选股数量

        Returns:
            候选股列表
        """
        logger.info("开始选股流程...")

        # 1. 获取全市场股票
        all_stocks = self._get_stock_pool()

        if not all_stocks:
            logger.error("无法获取股票列表")
            return []

        logger.info(f"获取到{len(all_stocks)}只股票，开始筛选...")

        # 2. 第一轮筛选：过滤不符合条件的股票
        filtered_stocks = self._first_round_filter(all_stocks)

        logger.info(f"第一轮筛选后剩余{len(filtered_stocks)}只股票")

        # 3. 第二轮筛选：技术面+基本面综合评估
        scored_stocks = self._second_round_score(filtered_stocks)

        logger.info(f"第二轮评分完成，共{len(scored_stocks)}只股票通过")

        # 4. 排序取前N只
        top_stocks = sorted(scored_stocks, key=lambda x: x['total_score'], reverse=True)[:limit]

        # 5. 生成买入建议
        candidates = self._generate_recommendations(top_stocks)

        # 6. 存入数据库
        self._save_candidates(candidates)

        logger.info(f"选股完成，输出{len(candidates)}只候选股")

        return candidates

    def _get_stock_pool(self) -> List[str]:
        """获取股票池"""
        # 获取全部A股
        stocks = self.baostock_api.get_stock_codes()

        # 过滤掉特殊股票（ST、退市等）
        # 这里可以添加更多过滤条件
        return stocks[:500]  # 限制数量以便测试

    def _first_round_filter(self, stocks: List[str]) -> List[str]:
        """第一轮筛选（快速过滤）"""
        filtered = []

        for stock in stocks:
            try:
                # 获取最近K线数据
                k_data = self.baostock_api.get_recent_k_data(stock, days=30)

                if k_data.empty:
                    continue

                # 快速判断条件
                last_close = k_data['close'].iloc[-1]

                # 1. 价格合理（大于1元）
                if last_close < 1:
                    continue

                # 2. 有一定成交量（避免僵尸股）
                avg_volume = k_data['volume'].iloc[-5:].mean()
                if avg_volume < 1000:
                    continue

                # 3. 非停牌（有最近数据）
                if len(k_data) < 10:
                    continue

                filtered.append(stock)

            except Exception as e:
                logger.warning(f"筛选股票{stock}时出错: {e}")
                continue

        return filtered

    def _second_round_score(self, stocks: List[str]) -> List[Dict[str, Any]]:
        """第二轮评分（技术面+基本面）"""
        scored_stocks = []

        # 并行处理
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(self._score_single_stock, stock): stock for stock in stocks}

            for future in as_completed(futures):
                stock = futures[future]
                try:
                    result = future.result()
                    if result and result.get('passed'):
                        scored_stocks.append(result)
                except Exception as e:
                    logger.warning(f"评分股票{stock}时出错: {e}")

        return scored_stocks

    def _score_single_stock(self, code: str) -> Optional[Dict[str, Any]]:
        """对单只股票评分"""
        try:
            # 获取K线数据
            k_data = self.baostock_api.get_recent_k_data(code, days=60)

            if k_data.empty:
                return None

            # 获取股票基本信息
            stock_info = self.baostock_api.get_stock_basic_info(code)
            name = stock_info.get('code_name', '')

            # 计算策略权重
            weights = {
                'technical': self.config.strategy.technical_weight,
                'fundamental': self.config.strategy.fundamental_weight,
            }

            # 技术面评分
            technical_result = self.strategy_manager.run_all(code, k_data)
            technical_score = 0
            for strategy_name in ['technical', 'macd', 'volume_breakout']:
                for r in technical_result:
                    if hasattr(r, 'score'):
                        technical_score += r.score * weights.get('technical', 0.4)

            # 基本面评分
            year = datetime.now().year
            fundamental_result = self.strategy_manager.strategies[3].evaluate(
                code, None,
                financial_data=None,
                year=year,
                quarter=4,
                pe_max=self.config.fundamental.pe_max,
                roe_min=self.config.fundamental.roe_min
            )
            fundamental_score = fundamental_result.get('score', 0) * weights.get('fundamental', 0.3)

            # 综合评分
            total_score = technical_score + fundamental_score

            passed = total_score >= 60

            return {
                'code': code,
                'name': name,
                'technical_score': technical_score,
                'fundamental_score': fundamental_score,
                'total_score': total_score,
                'passed': passed,
                'last_close': k_data['close'].iloc[-1],
                'signals': {
                    'technical': technical_result,
                    'fundamental': fundamental_result,
                }
            }

        except Exception as e:
            logger.error(f"评分{code}失败: {e}")
            return None

    def _generate_recommendations(self, scored_stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """生成买入建议"""
        candidates = []

        for stock in scored_stocks:
            # 计算买入区间
            last_close = stock['last_close']

            # 买入区间：当前价格的-2%到+2%
            buy_range_low = last_close * 0.98
            buy_range_high = last_close * 1.02

            # 止损价：当前价格的-5%
            stop_loss = last_close * (1 + self.config.risk.default_stop_loss)

            # 目标价：当前价格的+10%
            target_price = last_close * (1 + self.config.risk.default_take_profit)

            # 仓位建议
            score = stock['total_score']
            if score >= 80:
                position_advice = "建议仓位：可配置总资金的20%-30%"
            elif score >= 70:
                position_advice = "建议仓位：可配置总资金的10%-20%"
            else:
                position_advice = "建议仓位：可配置总资金的5%-10%"

            # 选入理由
            signals = stock.get('signals', {})
            reasons = []

            for s in signals.get('technical', []):
                if hasattr(s, 'signals') and s.signals:
                    for sig in s.signals:
                        if sig.get('passed'):
                            reasons.append(sig.get('name', ''))

            if signals.get('fundamental'):
                for sig in signals['fundamental'].get('signals', []):
                    if sig.get('passed'):
                        reasons.append(sig.get('name', ''))

            reason = "；".join(reasons[:5]) if reasons else "综合评分达标"

            candidate = {
                'code': stock['code'].replace('sh.', '').replace('sz.', ''),
                'name': stock['name'],
                'score': stock['total_score'],
                'buy_range_low': buy_range_low,
                'buy_range_high': buy_range_high,
                'target_price': target_price,
                'stop_loss': stop_loss,
                'position_advice': position_advice,
                'reason': reason,
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

    def get_top_by_technical(self, limit: int = 10) -> List[Dict[str, Any]]:
        """仅按技术面筛选"""
        stocks = self._get_stock_pool()
        filtered = self._first_round_filter(stocks)

        results = []
        for stock in filtered:
            k_data = self.baostock_api.get_recent_k_data(stock, days=60)

            if k_data.empty:
                continue

            strategy = TechnicalStrategy()
            result = strategy.evaluate(stock, k_data)

            if result['passed']:
                stock_info = self.baostock_api.get_stock_basic_info(stock)
                results.append({
                    'code': stock,
                    'name': stock_info.get('code_name', ''),
                    'score': result['score'],
                    'signals': result['signals'],
                })

        return sorted(results, key=lambda x: x['score'], reverse=True)[:limit]

    def get_top_by_fundamental(self, limit: int = 10) -> List[Dict[str, Any]]:
        """仅按基本面筛选"""
        stocks = self._get_stock_pool()

        results = []
        year = datetime.now().year

        for stock in stocks:
            strategy = FundamentalStrategy()
            result = strategy.evaluate(stock, None, year=year, quarter=4)

            if result['passed']:
                stock_info = self.baostock_api.get_stock_basic_info(stock)
                results.append({
                    'code': stock,
                    'name': stock_info.get('code_name', ''),
                    'score': result['score'],
                    'signals': result['signals'],
                })

        return sorted(results, key=lambda x: x['score'], reverse=True)[:limit]

    def refresh_realtime_prices(self) -> Dict[str, float]:
        """刷新候选股实时价格"""
        candidates = self.candidate_db.get_pending_candidates()

        if not candidates:
            return {}

        codes = [c.code for c in candidates]
        quotes = self.realtime_api.get_batch_quotes(codes)

        return {q['code']: q['price'] for q in quotes}