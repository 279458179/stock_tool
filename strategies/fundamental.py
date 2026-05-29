"""基本面选股策略"""
from typing import Dict, Any, List
import logging

from .base import BaseStrategy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FundamentalStrategy(BaseStrategy):
    """基本面策略"""

    name = "fundamental"
    description = "基本面分析策略（PE、ROE、盈利能力）"

    def get_required_data(self) -> List[str]:
        # 基本面策略需要额外的财务数据，不在K线中
        return []

    def evaluate(self, code: str, data, **kwargs) -> Dict[str, Any]:
        """
        基本面评估

        Args:
            code: 股票代码
            data: 这里data是财务数据字典
            **kwargs: 其他参数

        主要检测：
        1. PE估值
        2. ROE盈利能力
        3. 净利润增长率
        4. 负债率
        """
        signals = []

        financial_data = kwargs.get('financial_data', {})
        if not financial_data:
            # 尝试获取财务数据
            from data_sources.baostock_api import get_api
            api = get_api()

            year = str(kwargs.get('year', 2024))
            quarter = kwargs.get('quarter', 4)

            financial_data = api.get_performance_report(code, year, quarter)
            if not financial_data:
                return {'score': 0, 'passed': False, 'signals': [], 'details': {'error': '无财务数据'}}

        # 1. PE估值检测
        pe_signals = self._check_pe(financial_data, **kwargs)
        signals.extend(pe_signals)

        # 2. ROE检测
        roe_signals = self._check_roe(financial_data)
        signals.extend(roe_signals)

        # 3. 净利润增长检测
        growth_signals = self._check_growth(code, financial_data, **kwargs)
        signals.extend(growth_signals)

        # 4. EPS检测
        eps_signals = self._check_eps(financial_data)
        signals.extend(eps_signals)

        # 计算综合评分
        score = self.calculate_score(signals)

        # 判断是否通过
        passed = score >= 50 and any(s.get('passed', False) for s in signals)

        return {
            'score': score,
            'passed': passed,
            'signals': signals,
            'details': financial_data
        }

    def _check_pe(self, data: Dict[str, Any], **kwargs) -> List[Dict[str, Any]]:
        """检测PE估值"""
        signals = []

        pe = data.get('pe')
        pe_max = kwargs.get('pe_max', 30)

        # 如果没有PE，尝试从估值数据获取
        if pe is None or pe == 0:
            from data_sources.baostock_api import get_api
            api = get_api()
            valuation = api.get_valuation_data(data.get('code', ''))
            pe = valuation.get('pe', 0)

        if pe > 0:
            if pe <= pe_max * 0.7:  # PE低于阈值70%
                signals.append({
                    'name': '低估值',
                    'weight': 2,
                    'score': 90,
                    'passed': True,
                    'detail': f'PE={pe:.1f}，估值较低'
                })
            elif pe <= pe_max:
                signals.append({
                    'name': '合理估值',
                    'weight': 1.5,
                    'score': 70,
                    'passed': True,
                    'detail': f'PE={pe:.1f}，估值合理'
                })
            elif pe <= pe_max * 1.5:
                signals.append({
                    'name': '偏高估值',
                    'weight': 1,
                    'score': 40,
                    'passed': False,
                    'detail': f'PE={pe:.1f}，估值偏高'
                })
            else:
                signals.append({
                    'name': '高估值',
                    'weight': 1,
                    'score': 20,
                    'passed': False,
                    'detail': f'PE={pe:.1f}，估值过高'
                })
        else:
            signals.append({
                'name': 'PE数据缺失',
                'weight': 0.5,
                'score': 30,
                'passed': False,
                'detail': '无法获取PE数据'
            })

        return signals

    def _check_roe(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """检测ROE"""
        signals = []

        roe = data.get('roe', 0)

        if roe > 0:
            if roe >= 15:
                signals.append({
                    'name': '高ROE',
                    'weight': 2,
                    'score': 100,
                    'passed': True,
                    'detail': f'ROE={roe:.1f}%，盈利能力优秀'
                })
            elif roe >= 10:
                signals.append({
                    'name': '良好ROE',
                    'weight': 1.5,
                    'score': 80,
                    'passed': True,
                    'detail': f'ROE={roe:.1f}%，盈利能力良好'
                })
            elif roe >= 5:
                signals.append({
                    'name': '一般ROE',
                    'weight': 1,
                    'score': 50,
                    'passed': False,
                    'detail': f'ROE={roe:.1f}%'
                })
            else:
                signals.append({
                    'name': '低ROE',
                    'weight': 1,
                    'score': 20,
                    'passed': False,
                    'detail': f'ROE={roe:.1f}%，盈利能力较差'
                })
        else:
            signals.append({
                'name': 'ROE数据缺失',
                'weight': 0.5,
                'score': 30,
                'passed': False,
                'detail': '无法获取ROE数据'
            })

        return signals

    def _check_growth(self, code: str, data: Dict[str, Any], **kwargs) -> List[Dict[str, Any]]:
        """检测净利润增长率"""
        signals = []

        from data_sources.baostock_api import get_api
        api = get_api()

        year = str(kwargs.get('year', 2024))
        quarter = kwargs.get('quarter', 4)

        growth_data = api.get_growth_report(code, year, quarter)

        if growth_data:
            yoy_profit = growth_data.get('YOYNetProfit', 0)

            if yoy_profit > 0:
                if yoy_profit >= 30:
                    signals.append({
                        'name': '高增长',
                        'weight': 2,
                        'score': 100,
                        'passed': True,
                        'detail': f'净利润同比增长{yoy_profit:.1f}%'
                    })
                elif yoy_profit >= 15:
                    signals.append({
                        'name': '稳健增长',
                        'weight': 1.5,
                        'score': 80,
                        'passed': True,
                        'detail': f'净利润同比增长{yoy_profit:.1f}%'
                    })
                elif yoy_profit >= 5:
                    signals.append({
                        'name': '小幅增长',
                        'weight': 1,
                        'score': 60,
                        'passed': True,
                        'detail': f'净利润同比增长{yoy_profit:.1f}%'
                    })
                else:
                    signals.append({
                        'name': '增长乏力',
                        'weight': 1,
                        'score': 40,
                        'passed': False,
                        'detail': f'净利润同比增长{yoy_profit:.1f}%'
                    })
            else:
                signals.append({
                    'name': '业绩下滑',
                    'weight': 1,
                    'score': 20,
                    'passed': False,
                    'detail': f'净利润同比下降{abs(yoy_profit):.1f}%'
                })

        return signals

    def _check_eps(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """检测EPS"""
        signals = []

        eps = data.get('eps', 0)

        if eps > 0:
            if eps >= 1:
                signals.append({
                    'name': '高EPS',
                    'weight': 1,
                    'score': 80,
                    'passed': True,
                    'detail': f'EPS={eps:.2f}元'
                })
            elif eps >= 0.3:
                signals.append({
                    'name': '中等EPS',
                    'weight': 0.5,
                    'score': 60,
                    'passed': True,
                    'detail': f'EPS={eps:.2f}元'
                })
            else:
                signals.append({
                    'name': '低EPS',
                    'weight': 0.5,
                    'score': 30,
                    'passed': False,
                    'detail': f'EPS={eps:.2f}元'
                })

        return signals


class QualityStockStrategy(BaseStrategy):
    """优质股票筛选策略"""

    name = "quality"
    description = "优质股票筛选（连续盈利+稳定增长）"

    def get_required_data(self) -> List[str]:
        return []

    def evaluate(self, code: str, data, **kwargs) -> Dict[str, Any]:
        """
        筛选优质股票

        主要检测：
        1. 连续盈利年数
        2. ROE稳定性
        3. 净利润稳定性
        """
        signals = []

        from data_sources.baostock_api import get_api
        api = get_api()

        current_year = kwargs.get('year', 2024)
        profit_years = kwargs.get('profit_years', 3)

        # 检查连续盈利
        consecutive_profit = 0
        for year in range(int(current_year) - profit_years, int(current_year)):
            perf = api.get_performance_report(code, str(year), 4)
            if perf and perf.get('netProfit', 0) > 0:
                consecutive_profit += 1

        if consecutive_profit >= profit_years:
            signals.append({
                'name': '连续盈利',
                'weight': 2,
                'score': 100,
                'passed': True,
                'detail': f'连续{consecutive_profit}年盈利'
            })
        elif consecutive_profit >= profit_years - 1:
            signals.append({
                'name': '基本盈利',
                'weight': 1.5,
                'score': 70,
                'passed': True,
                'detail': f'{consecutive_profit}年盈利'
            })
        else:
            signals.append({
                'name': '盈利不稳定',
                'weight': 1,
                'score': 30,
                'passed': False,
                'detail': f'仅{consecutive_profit}年盈利'
            })

        # 检查ROE稳定性
        roe_list = []
        for year in range(int(current_year) - 3, int(current_year)):
            perf = api.get_performance_report(code, str(year), 4)
            if perf and perf.get('roe', 0) > 0:
                roe_list.append(perf['roe'])

        if len(roe_list) >= 2:
            avg_roe = sum(roe_list) / len(roe_list)
            if avg_roe >= 10:
                signals.append({
                    'name': '稳定ROE',
                    'weight': 1.5,
                    'score': 90,
                    'passed': True,
                    'detail': f'平均ROE={avg_roe:.1f}%'
                })

        score = self.calculate_score(signals)
        passed = score >= 70

        return {
            'score': score,
            'passed': passed,
            'signals': signals,
            'details': {
                'consecutive_profit_years': consecutive_profit,
                'avg_roe': avg_roe if roe_list else 0,
            }
        }


class LowValuationStrategy(BaseStrategy):
    """低估值策略"""

    name = "low_valuation"
    description = "低估值股票筛选"

    def get_required_data(self) -> List[str]:
        return []

    def evaluate(self, code: str, data, **kwargs) -> Dict[str, Any]:
        """筛选低估值股票"""
        signals = []

        from data_sources.baostock_api import get_api
        api = get_api()

        valuation = api.get_valuation_data(code)
        pe = valuation.get('pe', 0)
        pb = valuation.get('pb', 0)

        pe_max = kwargs.get('pe_max', 30)
        pb_max = kwargs.get('pb_max', 3)

        # PE检测
        if pe > 0 and pe <= pe_max * 0.6:
            signals.append({
                'name': '低估PE',
                'weight': 2,
                'score': 100,
                'passed': True,
                'detail': f'PE={pe:.1f}'
            })
        elif pe > 0 and pe <= pe_max:
            signals.append({
                'name': '合理PE',
                'weight': 1,
                'score': 70,
                'passed': True,
                'detail': f'PE={pe:.1f}'
            })

        # PB检测
        if pb > 0 and pb <= pb_max * 0.6:
            signals.append({
                'name': '低估PB',
                'weight': 1.5,
                'score': 100,
                'passed': True,
                'detail': f'PB={pb:.1f}'
            })
        elif pb > 0 and pb <= pb_max:
            signals.append({
                'name': '合理PB',
                'weight': 1,
                'score': 70,
                'passed': True,
                'detail': f'PB={pb:.1f}'
            })

        score = self.calculate_score(signals)
        passed = score >= 80

        return {
            'score': score,
            'passed': passed,
            'signals': signals,
            'details': valuation
        }