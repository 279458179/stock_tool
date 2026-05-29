"""辅助工具函数"""
import re
from datetime import datetime, timedelta
from typing import List, Optional


def format_stock_code(code: str) -> str:
    """
    格式化股票代码为标准格式

    Args:
        code: 原始代码，如600519、sh600519、sh.600519等

    Returns:
        标准格式：sh600519 或 sz600519
    """
    # 去除所有前缀和分隔符
    clean_code = re.sub(r'[shsz\.]', '', code.lower())

    # 根据代码判断市场
    if clean_code.startswith('6'):
        return f'sh{clean_code}'
    else:
        return f'sz{clean_code}'


def format_code_simple(code: str) -> str:
    """
    格式化股票代码为简化格式

    Args:
        code: 原始代码

    Returns:
        简化格式：600519
    """
    clean_code = re.sub(r'[shsz\.]', '', code.lower())
    return clean_code


def is_trading_day(date: Optional[datetime] = None) -> bool:
    """
    判断是否为交易日

    Args:
        date: 日期，默认今天

    Returns:
        是否为交易日
    """
    if date is None:
        date = datetime.now()

    # 周末不交易
    if date.weekday() >= 5:
        return False

    # 简单判断，实际需要考虑节假日
    # 可以接入交易日历API
    return True


def get_next_trading_day(date: Optional[datetime] = None) -> datetime:
    """
    获取下一个交易日

    Args:
        date: 起始日期

    Returns:
        下一个交易日
    """
    if date is None:
        date = datetime.now()

    next_day = date + timedelta(days=1)

    while not is_trading_day(next_day):
        next_day += timedelta(days=1)

    return next_day


def calculate_profit_pct(cost: float, current: float) -> float:
    """
    计算盈亏比例

    Args:
        cost: 成本价
        current: 当前价

    Returns:
        盈亏比例（百分比）
    """
    if cost <= 0:
        return 0

    return (current - cost) / cost * 100


def calculate_position_value(price: float, shares: int) -> float:
    """
    计算持仓市值

    Args:
        price: 价格
        shares: 股数

    Returns:
        市值
    """
    return price * shares


def calculate_shares_by_budget(budget: float, price: float, min_shares: int = 100) -> int:
    """
    根据预算计算可买股数

    Args:
        budget: 预算金额
        price: 价格
        min_shares: 最小购买单位（A股为100股）

    Returns:
        可买股数
    """
    if price <= 0:
        return 0

    max_shares = int(budget / price)

    # 取整到最小单位
    shares = (max_shares // min_shares) * min_shares

    return shares


def parse_time(time_str: str) -> datetime:
    """
    解析时间字符串

    Args:
        time_str: 时间字符串，如 "09:30"

    Returns:
        datetime对象
    """
    today = datetime.now()

    if ':' in time_str:
        parts = time_str.split(':')
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        second = int(parts[2]) if len(parts) > 2 else 0
    else:
        hour = int(time_str)
        minute = 0
        second = 0

    return today.replace(hour=hour, minute=minute, second=second)


def is_in_time_range(start_time: str, end_time: str) -> bool:
    """
    判断当前时间是否在指定范围内

    Args:
        start_time: 开始时间，如 "09:30"
        end_time: 结束时间，如 "11:30"

    Returns:
        是否在范围内
    """
    now = datetime.now()

    start = parse_time(start_time)
    end = parse_time(end_time)

    return start <= now <= end


def get_market_status() -> str:
    """
    获取市场状态

    Returns:
        状态：trading/pre_market/auction/closed
    """
    current_time = datetime.now().strftime("%H:%M")

    # A股交易时间
    if "09:15" <= current_time < "09:25":
        return "auction"
    elif "09:30" <= current_time < "11:30":
        return "trading"
    elif "13:00" <= current_time < "15:00":
        return "trading"
    elif "09:25" <= current_time < "09:30":
        return "pre_market"
    else:
        return "closed"


def validate_stock_code(code: str) -> bool:
    """
    验证股票代码格式

    Args:
        code: 股票代码

    Returns:
        是否有效
    """
    # A股代码：6位数字
    clean_code = format_code_simple(code)

    if len(clean_code) != 6:
        return False

    if not clean_code.isdigit():
        return False

    # 验证市场代码
    # 上海：60xxxx, 68xxxx
    # 深圳：00xxxx, 30xxxx

    if clean_code.startswith('6'):
        return True
    elif clean_code.startswith('0') or clean_code.startswith('3'):
        return True

    return False


def chunk_list(lst: List, chunk_size: int) -> List[List]:
    """
    将列表分块

    Args:
        lst: 原列表
        chunk_size: 每块大小

    Returns:
        分块后的列表
    """
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def safe_float(value: any, default: float = 0.0) -> float:
    """
    安全转换为浮点数

    Args:
        value: 原值
        default: 默认值

    Returns:
        浮点数
    """
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value: any, default: int = 0) -> int:
    """
    安全转换为整数

    Args:
        value: 原值
        default: 默认值

    Returns:
        整数
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return default