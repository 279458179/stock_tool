"""配置管理模块"""
import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class DataSourceConfig:
    primary: str = "baostock"
    realtime: str = "tencent"


@dataclass
class StrategyConfig:
    technical_weight: float = 0.4
    fundamental_weight: float = 0.3
    capital_weight: float = 0.3


@dataclass
class TechnicalConfig:
    ma_periods: list = field(default_factory=lambda: [5, 10, 20, 60])
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    volume_ratio: float = 2.0


@dataclass
class FundamentalConfig:
    pe_max: int = 30
    roe_min: int = 10
    profit_years: int = 3


@dataclass
class RiskConfig:
    default_stop_loss: float = -0.05
    default_take_profit: float = 0.10
    position_alert: float = 0.03


@dataclass
class SelectorConfig:
    min_price: float = 5.0      # 最低价格5元（排除低价垃圾股）
    max_price: float = 50.0     # 最高价格50元
    min_score: float = 50.0     # 最低评分门槛
    min_signals: int = 2        # 最少共振信号数
    max_pct_1d: float = 8.0     # 追高过滤：1日涨幅>8%排除
    max_open_pct: float = 6.0   # 高开>6%且评分<60→剔除
    max_open_pct_hard: float = 8.0  # 高开>8%→一律剔除
    stock_pool: str = "hs300"   # 选股池：hs300=all_market


@dataclass
class NotificationConfig:
    desktop: bool = True
    sound: bool = True
    feishu_webhook: str = ""


@dataclass
class TradingHoursConfig:
    pre_market_start: str = "09:15"
    market_open: str = "09:30"
    market_close: str = "15:00"
    auction_end: str = "09:25"


@dataclass
class Config:
    data_source: DataSourceConfig = field(default_factory=DataSourceConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    technical: TechnicalConfig = field(default_factory=TechnicalConfig)
    fundamental: FundamentalConfig = field(default_factory=FundamentalConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    selector: SelectorConfig = field(default_factory=SelectorConfig)
    notification: NotificationConfig = field(default_factory=NotificationConfig)
    trading_hours: TradingHoursConfig = field(default_factory=TradingHoursConfig)

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        """从YAML文件加载配置"""
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        config = cls()

        if 'data_source' in data:
            config.data_source = DataSourceConfig(**data['data_source'])
        if 'strategy' in data:
            config.strategy = StrategyConfig(**data['strategy'])
        if 'technical' in data:
            config.technical = TechnicalConfig(**data['technical'])
        if 'fundamental' in data:
            config.fundamental = FundamentalConfig(**data['fundamental'])
        if 'risk' in data:
            config.risk = RiskConfig(**data['risk'])
        if 'selector' in data:
            config.selector = SelectorConfig(**data['selector'])
        if 'notification' in data:
            config.notification = NotificationConfig(**data['notification'])
        if 'trading_hours' in data:
            config.trading_hours = TradingHoursConfig(**data['trading_hours'])

        return config

    def to_yaml(self, path: str):
        """保存配置到YAML文件"""
        data = {
            'data_source': {
                'primary': self.data_source.primary,
                'realtime': self.data_source.realtime,
            },
            'strategy': {
                'technical_weight': self.strategy.technical_weight,
                'fundamental_weight': self.strategy.fundamental_weight,
                'capital_weight': self.strategy.capital_weight,
            },
            'technical': {
                'ma_periods': self.technical.ma_periods,
                'macd_fast': self.technical.macd_fast,
                'macd_slow': self.technical.macd_slow,
                'macd_signal': self.technical.macd_signal,
                'volume_ratio': self.technical.volume_ratio,
            },
            'fundamental': {
                'pe_max': self.fundamental.pe_max,
                'roe_min': self.fundamental.roe_min,
                'profit_years': self.fundamental.profit_years,
            },
            'risk': {
                'default_stop_loss': self.risk.default_stop_loss,
                'default_take_profit': self.risk.default_take_profit,
                'position_alert': self.risk.position_alert,
            },
            'selector': {
                'min_price': self.selector.min_price,
                'max_price': self.selector.max_price,
                'min_score': self.selector.min_score,
                'min_signals': self.selector.min_signals,
                'max_pct_1d': self.selector.max_pct_1d,
                'max_open_pct': self.selector.max_open_pct,
                'max_open_pct_hard': self.selector.max_open_pct_hard,
                'stock_pool': self.selector.stock_pool,
            },
            'notification': {
                'desktop': self.notification.desktop,
                'sound': self.notification.sound,
                'feishu_webhook': self.notification.feishu_webhook,
            },
            'trading_hours': {
                'pre_market_start': self.trading_hours.pre_market_start,
                'market_open': self.trading_hours.market_open,
                'market_close': self.trading_hours.market_close,
                'auction_end': self.trading_hours.auction_end,
            },
        }

        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def get_config_path() -> Path:
    """获取配置文件路径"""
    # 优先使用当前目录的配置
    local_config = Path("stock_tool/config.yaml")
    if local_config.exists():
        return local_config

    # 其次使用用户目录下的配置
    user_config = Path.home() / ".stock_tool" / "config.yaml"
    if user_config.exists():
        return user_config

    # 默认使用项目目录下的配置
    return Path(__file__).parent / "config.yaml"


def load_config() -> Config:
    """加载配置"""
    config_path = get_config_path()
    if config_path.exists():
        return Config.from_yaml(str(config_path))
    return Config()


# 全局配置实例
_config: Optional[Config] = None


def get_config() -> Config:
    """获取全局配置实例"""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> Config:
    """重新加载配置"""
    global _config
    _config = load_config()
    return _config
