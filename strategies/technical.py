"""技术面选股策略"""
import pandas as pd
import numpy as np
from typing import Dict, Any, List
from .base import BaseStrategy


class TechnicalStrategy(BaseStrategy):
    """技术面策略"""

    name = "technical"
    description = "技术面分析策略（均线、MACD、成交量）"

    def get_required_data(self) -> List[str]:
        return ['open', 'high', 'low', 'close', 'volume']

    def evaluate(self, code: str, data: pd.DataFrame, **kwargs) -> Dict[str, Any]:
        """
        技术面评估

        主要检测：
        1. 均线系统（多头排列）
        2. MACD金叉
        3. 放量突破
        4. 趋势强度
        """
        if not self.check_requirements(data) or data.empty:
            return {'score': 0, 'passed': False, 'signals': [], 'details': {}}

        signals = []

        # 1. 均线系统检测
        ma_signals = self._check_ma_system(data)
        signals.extend(ma_signals)

        # 2. MACD检测
        macd_signals = self._check_macd(data)
        signals.extend(macd_signals)

        # 3. 放量检测
        volume_signals = self._check_volume(data)
        signals.extend(volume_signals)

        # 4. 趋势检测
        trend_signals = self._check_trend(data)
        signals.extend(trend_signals)

        # 5. 形态检测
        pattern_signals = self._check_patterns(data)
        signals.extend(pattern_signals)

        # 计算综合评分
        score = self.calculate_score(signals)

        # 判断是否通过
        passed = score >= 60 and any(s.get('passed', False) for s in signals)

        return {
            'score': score,
            'passed': passed,
            'signals': signals,
            'details': {
                'last_close': data['close'].iloc[-1],
                'last_volume': data['volume'].iloc[-1],
                'ma5': self._get_ma(data, 5).iloc[-1],
                'ma10': self._get_ma(data, 10).iloc[-1],
                'ma20': self._get_ma(data, 20).iloc[-1],
                'ma60': self._get_ma(data, 60).iloc[-1] if len(data) >= 60 else None,
            }
        }

    def _get_ma(self, data: pd.DataFrame, period: int) -> pd.Series:
        """计算均线"""
        return data['close'].rolling(window=period).mean()

    def _check_ma_system(self, data: pd.DataFrame) -> List[Dict[str, Any]]:
        """检测均线系统"""
        signals = []

        ma5 = self._get_ma(data, 5)
        ma10 = self._get_ma(data, 10)
        ma20 = self._get_ma(data, 20)
        ma60 = self._get_ma(data, 60) if len(data) >= 60 else None

        last_close = data['close'].iloc[-1]

        # 均线多头排列检测
        if ma60 is not None and ma5.iloc[-1] > ma10.iloc[-1] > ma20.iloc[-1] > ma60.iloc[-1]:
            signals.append({
                'name': '均线多头排列',
                'weight': 2,
                'score': 100,
                'passed': True,
                'detail': 'MA5>MA10>MA20>MA60'
            })
        elif ma5.iloc[-1] > ma10.iloc[-1] > ma20.iloc[-1]:
            signals.append({
                'name': '均线多头排列（短）',
                'weight': 1.5,
                'score': 80,
                'passed': True,
                'detail': 'MA5>MA10>MA20'
            })
        else:
            signals.append({
                'name': '均线多头排列',
                'weight': 2,
                'score': 20,
                'passed': False,
                'detail': '均线未多头排列'
            })

        # 价格站上均线检测
        above_count = 0
        for ma in [ma5, ma10, ma20]:
            if last_close > ma.iloc[-1]:
                above_count += 1

        above_score = above_count * 30
        signals.append({
            'name': '价格站上均线',
            'weight': 1,
            'score': above_score,
            'passed': above_count >= 2,
            'detail': f'站上{above_count}条均线'
        })

        return signals

    def _check_macd(self, data: pd.DataFrame) -> List[Dict[str, Any]]:
        """检测MACD"""
        signals = []

        # 计算MACD
        exp12 = data['close'].ewm(span=12, adjust=False).mean()
        exp26 = data['close'].ewm(span=26, adjust=False).mean()
        dif = exp12 - exp26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd = (dif - dea) * 2

        # MACD金叉检测
        if len(macd) >= 2:
            # DIF上穿DEA
            if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2]:
                signals.append({
                    'name': 'MACD金叉',
                    'weight': 2,
                    'score': 100,
                    'passed': True,
                    'detail': 'DIF上穿DEA，金叉信号'
                })
            # DIF在DEA上方
            elif dif.iloc[-1] > dea.iloc[-1]:
                signals.append({
                    'name': 'MACD多头',
                    'weight': 1,
                    'score': 70,
                    'passed': True,
                    'detail': 'DIF>DEA'
                })
            else:
                signals.append({
                    'name': 'MACD状态',
                    'weight': 1,
                    'score': 20,
                    'passed': False,
                    'detail': 'DIF<DEA'
                })

            # MACD柱状图转正
            if macd.iloc[-1] > 0 and macd.iloc[-2] <= 0:
                signals.append({
                    'name': 'MACD柱转正',
                    'weight': 1.5,
                    'score': 90,
                    'passed': True,
                    'detail': 'MACD柱由负转正'
                })
            elif macd.iloc[-1] > 0:
                signals.append({
                    'name': 'MACD柱为正',
                    'weight': 0.5,
                    'score': 50,
                    'passed': True,
                    'detail': 'MACD柱为正'
                })

        return signals

    def _check_volume(self, data: pd.DataFrame) -> List[Dict[str, Any]]:
        """检测成交量"""
        signals = []

        if len(data) < 5:
            return signals

        # 计算平均成交量
        avg_volume = data['volume'].iloc[-5:].mean()
        last_volume = data['volume'].iloc[-1]

        # 放量检测
        volume_ratio = last_volume / avg_volume if avg_volume > 0 else 0

        if volume_ratio >= 2:
            signals.append({
                'name': '放量突破',
                'weight': 2,
                'score': 100,
                'passed': True,
                'detail': f'量比{volume_ratio:.1f}倍'
            })
        elif volume_ratio >= 1.5:
            signals.append({
                'name': '温和放量',
                'weight': 1,
                'score': 70,
                'passed': True,
                'detail': f'量比{volume_ratio:.1f}倍'
            })
        elif volume_ratio < 0.5:
            signals.append({
                'name': '缩量',
                'weight': 0.5,
                'score': 30,
                'passed': False,
                'detail': '成交量萎缩'
            })

        return signals

    def _check_trend(self, data: pd.DataFrame) -> List[Dict[str, Any]]:
        """检测趋势"""
        signals = []

        if len(data) < 10:
            return signals

        # 计算最近N天的涨跌幅
        returns = data['close'].pct_change().dropna()

        # 最近5天趋势
        recent5_return = returns.iloc[-5:].sum()

        if recent5_return >= 0.05:
            signals.append({
                'name': '短期上涨趋势',
                'weight': 1.5,
                'score': 90,
                'passed': True,
                'detail': f'5日涨幅{recent5_return*100:.1f}%'
            })
        elif recent5_return >= 0.02:
            signals.append({
                'name': '温和上涨',
                'weight': 1,
                'score': 70,
                'passed': True,
                'detail': f'5日涨幅{recent5_return*100:.1f}%'
            })
        elif recent5_return < -0.03:
            signals.append({
                'name': '下跌趋势',
                'weight': 1,
                'score': 20,
                'passed': False,
                'detail': f'5日跌幅{recent5_return*100:.1f}%'
            })

        return signals

    def _check_patterns(self, data: pd.DataFrame) -> List[Dict[str, Any]]:
        """检测K线形态"""
        signals = []

        if len(data) < 3:
            return signals

        last = data.iloc[-1]
        prev = data.iloc[-2]
        prev2 = data.iloc[-3]

        # 阳线检测
        if last['close'] > last['open']:
            # 大阳线
            if (last['close'] - last['open']) / last['open'] >= 0.03:
                signals.append({
                    'name': '大阳线',
                    'weight': 1.5,
                    'score': 85,
                    'passed': True,
                    'detail': '涨幅>3%的阳线'
                })
            else:
                signals.append({
                    'name': '阳线',
                    'weight': 0.5,
                    'score': 60,
                    'passed': True,
                    'detail': '收盘>开盘'
                })

        # 连续阳线
        if prev['close'] > prev['open'] and last['close'] > last['open']:
            signals.append({
                'name': '连续阳线',
                'weight': 1,
                'score': 80,
                'passed': True,
                'detail': '连续2日阳线'
            })

        # 突破前高
        if len(data) >= 10:
            recent_high = data['high'].iloc[-10:-1].max()
            if last['close'] > recent_high:
                signals.append({
                    'name': '突破前高',
                    'weight': 2,
                    'score': 95,
                    'passed': True,
                    'detail': f'突破{recent5_return}日高点'
                })

        return signals


class MACDStrategy(BaseStrategy):
    """MACD专项策略"""

    name = "macd"
    description = "MACD金叉专项检测"

    def get_required_data(self) -> List[str]:
        return ['close']

    def evaluate(self, code: str, data: pd.DataFrame, **kwargs) -> Dict[str, Any]:
        if not self.check_requirements(data) or len(data) < 30:
            return {'score': 0, 'passed': False, 'signals': [], 'details': {}}

        signals = []

        # 计算MACD
        exp12 = data['close'].ewm(span=12, adjust=False).mean()
        exp26 = data['close'].ewm(span=26, adjust=False).mean()
        dif = exp12 - exp26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd = (dif - dea) * 2

        # 检测金叉
        # 1. 刚金叉（今天DIF上穿DEA）
        if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2]:
            # 在零轴上方金叉更强
            if dif.iloc[-1] > 0:
                signals.append({
                    'name': '零轴上方金叉',
                    'weight': 3,
                    'score': 100,
                    'passed': True,
                    'detail': '强金叉信号'
                })
            else:
                signals.append({
                    'name': '零轴下方金叉',
                    'weight': 2,
                    'score': 80,
                    'passed': True,
                    'detail': '金叉信号'
                })

        # 2. 5天内金叉
        for i in range(2, 6):
            if len(dif) >= i + 1:
                if dif.iloc[-i] > dea.iloc[-i] and dif.iloc[-i-1] <= dea.iloc[-i-1]:
                    signals.append({
                        'name': f'近期金叉（{-i+1}日前）',
                        'weight': 1.5,
                        'score': 75,
                        'passed': True,
                        'detail': f'{-i+1}日前出现金叉'
                    })
                    break

        score = self.calculate_score(signals)
        passed = score >= 70

        return {
            'score': score,
            'passed': passed,
            'signals': signals,
            'details': {
                'dif': dif.iloc[-1],
                'dea': dea.iloc[-1],
                'macd': macd.iloc[-1],
            }
        }


class VolumeBreakoutStrategy(BaseStrategy):
    """放量突破策略"""

    name = "volume_breakout"
    description = "放量突破检测"

    def get_required_data(self) -> List[str]:
        return ['close', 'volume', 'high']

    def evaluate(self, code: str, data: pd.DataFrame, **kwargs) -> Dict[str, Any]:
        if not self.check_requirements(data) or len(data) < 20:
            return {'score': 0, 'passed': False, 'signals': [], 'details': {}}

        signals = []

        # 计算平均成交量
        avg_volume_5 = data['volume'].iloc[-5:-1].mean()
        avg_volume_20 = data['volume'].iloc[-20:-1].mean()
        last_volume = data['volume'].iloc[-1]

        volume_ratio_5 = last_volume / avg_volume_5 if avg_volume_5 > 0 else 0
        volume_ratio_20 = last_volume / avg_volume_20 if avg_volume_20 > 0 else 0

        # 突破前高
        recent_high_20 = data['high'].iloc[-20:-1].max()
        last_close = data['close'].iloc[-1]

        # 放量突破前高
        if last_close > recent_high_20:
            if volume_ratio_5 >= 2:
                signals.append({
                    'name': '放量突破',
                    'weight': 3,
                    'score': 100,
                    'passed': True,
                    'detail': f'突破20日高点，量比{volume_ratio_5:.1f}'
                })
            elif volume_ratio_5 >= 1.5:
                signals.append({
                    'name': '温和放量突破',
                    'weight': 2,
                    'score': 80,
                    'passed': True,
                    'detail': f'突破20日高点'
                })
            else:
                signals.append({
                    'name': '突破前高（缩量）',
                    'weight': 1,
                    'score': 50,
                    'passed': False,
                    'detail': '突破但量不足'
                })

        score = self.calculate_score(signals)
        passed = score >= 70

        return {
            'score': score,
            'passed': passed,
            'signals': signals,
            'details': {
                'volume_ratio_5': volume_ratio_5,
                'volume_ratio_20': volume_ratio_20,
                'recent_high': recent_high_20,
                'last_close': last_close,
            }
        }