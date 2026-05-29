"""BaoStock数据源接口封装"""
import baostock as bs
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BaoStockAPI:
    """BaoStock数据接口封装类"""

    def __init__(self):
        self._logged_in = False

    def login(self) -> bool:
        """登录BaoStock"""
        if self._logged_in:
            return True

        lg = bs.login()
        if lg.error_code != '0':
            logger.error(f"BaoStock登录失败: {lg.error_msg}")
            return False

        self._logged_in = True
        logger.info("BaoStock登录成功")
        return True

    def logout(self):
        """登出BaoStock"""
        if self._logged_in:
            bs.logout()
            self._logged_in = False

    def get_all_stocks(self, date: Optional[str] = None) -> List[Dict[str, str]]:
        """获取全部A股股票列表"""
        if not self.login():
            return []

        if date is None:
            # 使用一个确定的交易日（避免当前日期可能不是交易日）
            date = '2024-01-15'

        rs = bs.query_all_stock(day=date)
        if rs.error_code != '0':
            logger.error(f"获取股票列表失败: {rs.error_msg}")
            return []

        stocks = []
        while rs.next():
            row = rs.get_row_data()
            code = row[0]
            simple_code = code.replace('sh.', '').replace('sz.', '')

            # A股股票过滤规则:
            # 上海主板: 60xxxx
            # 深圳主板: 00xxxx (排除指数000xxx和399xxx)
            # 创业板: 30xxxx
            # 科创板: 688xxx

            is_a_stock = False
            if simple_code.startswith('6'):
                # 60xxxx 上海主板, 688xxx 科创板
                is_a_stock = True
            elif simple_code.startswith('00') and len(simple_code) == 6:
                # 002xxx 深圳中小板, 001xxx 深圳主板
                # 排除指数: 000001(上证指数)等
                if not simple_code.startswith('000'):
                    is_a_stock = True
            elif simple_code.startswith('30'):
                # 创业板
                is_a_stock = True

            if is_a_stock:
                stocks.append({
                    'code': code,
                    'code_simple': simple_code,
                    'name': row[1],
                    'type': row[2] if len(row) > 2 else ''
                })

        logger.info(f"获取到{len(stocks)}只A股股票")
        return stocks

    def get_stock_codes(self) -> List[str]:
        """获取A股股票代码列表（简化格式）"""
        stocks = self.get_all_stocks()
        return [s['code'] for s in stocks]

    def get_k_data(
        self,
        code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjustflag: str = "3"
    ) -> pd.DataFrame:
        """
        获取K线数据

        Args:
            code: 股票代码（如sh.600000）
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
            frequency: d=日线, w=周线, m=月线
            adjustflag: 1=前复权, 2=后复权, 3=不复权

        Returns:
            DataFrame包含K线数据
        """
        if not self.login():
            return pd.DataFrame()

        rs = bs.query_history_k_data_plus(
            code,
            "date,code,open,high,low,close,preclose,volume,amount,turn,pctChg",
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            adjustflag=adjustflag
        )

        if rs.error_code != '0':
            logger.error(f"获取K线数据失败: {rs.error_msg}")
            return pd.DataFrame()

        data_list = []
        while rs.next():
            data_list.append(rs.get_row_data())

        if not data_list:
            return pd.DataFrame()

        df = pd.DataFrame(data_list, columns=rs.fields)
        # 转换数值类型
        numeric_cols = ['open', 'high', 'low', 'close', 'preclose', 'volume', 'amount', 'turn', 'pctChg']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        return df

    def get_recent_k_data(self, code: str, days: int = 60) -> pd.DataFrame:
        """获取最近N天的K线数据"""
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days + 10)).strftime("%Y-%m-%d")
        return self.get_k_data(code, start_date, end_date)

    def get_stock_basic_info(self, code: str) -> Dict[str, Any]:
        """获取股票基本信息"""
        if not self.login():
            return {}

        rs = bs.query_stock_basic(code=code)
        if rs.error_code != '0':
            return {}

        info = {}
        while rs.next():
            row = rs.get_row_data()
            info = {
                'code': row[0],
                'code_name': row[1],
                'ipoDate': row[2],
                'outDate': row[3],
                'type': row[4],
                'status': row[5],
            }
            break

        return info

    def get_stock_industry(self, code: str) -> Dict[str, str]:
        """获取股票行业分类"""
        if not self.login():
            return {}

        rs = bs.query_stock_industry(code=code)
        if rs.error_code != '0':
            return {}

        info = {}
        while rs.next():
            row = rs.get_row_data()
            info = {
                'code': row[0],
                'industry': row[1],
                'industryClassification': row[2],
            }
            break

        return info

    def get_performance_report(
        self,
        code: str,
        year: str,
        quarter_type: int = 4
    ) -> Dict[str, Any]:
        """
        获取季度业绩报表

        Args:
            code: 股票代码
            year: 年份
            quarter_type: 季度 1/2/3/4
        """
        if not self.login():
            return {}

        rs = bs.query_performance_report(code=code, year=year, quarterType=quarter_type)
        if rs.error_code != '0':
            return {}

        data = {}
        while rs.next():
            row = rs.get_row_data()
            data = {
                'code': row[0],
                'pubDate': row[1],
                'statDate': row[2],
                'updateDate': row[3],
                'netProfit': float(row[4]) if row[4] else 0,
                'netProfitRate': float(row[5]) if row[5] else 0,
                'operatingRevenue': float(row[6]) if row[6] else 0,
                'operatingRevenueRate': float(row[7]) if row[7] else 0,
                'roe': float(row[8]) if row[8] else 0,
                'roa': float(row[9]) if row[9] else 0,
                'eps': float(row[10]) if row[10] else 0,
                'bps': float(row[11]) if row[11] else 0,
            }
            break

        return data

    def get_growth_report(self, code: str, year: str, quarter_type: int = 4) -> Dict[str, Any]:
        """获取季度成长能力报表"""
        if not self.login():
            return {}

        rs = bs.query_growth_report(code=code, year=year, quarterType=quarter_type)
        if rs.error_code != '0':
            return {}

        data = {}
        while rs.next():
            row = rs.get_row_data()
            data = {
                'code': row[0],
                'pubDate': row[1],
                'statDate': row[2],
                'YOYNetProfit': float(row[3]) if row[3] else 0,
                'YOYEPSBasic': float(row[4]) if row[4] else 0,
                'YOYOpeartingRevenue': float(row[5]) if row[5] else 0,
                'YOYOperatingProfit': float(row[6]) if row[6] else 0,
                'YOYSalesCost': float(row[7]) if row[7] else 0,
            }
            break

        return data

    def get_balance_report(self, code: str, year: str, quarter_type: int = 4) -> Dict[str, Any]:
        """获取季度资产负债表"""
        if not self.login():
            return {}

        rs = bs.query_balance_report(code=code, year=year, quarterType=quarter_type)
        if rs.error_code != '0':
            return {}

        data = {}
        while rs.next():
            row = rs.get_row_data()
            data = {
                'code': row[0],
                'pubDate': row[1],
                'statDate': row[2],
                'totalAssets': float(row[3]) if row[3] else 0,
                'totalLiab': float(row[4]) if row[4] else 0,
                'currentAssets': float(row[5]) if row[5] else 0,
                'currentLiab': float(row[6]) if row[6] else 0,
                'totalEquity': float(row[7]) if row[7] else 0,
            }
            break

        return data

    def get_dupont_report(self, code: str, year: str, quarter_type: int = 4) -> Dict[str, Any]:
        """获取杜邦分析数据"""
        if not self.login():
            return {}

        rs = bs.query_dupont_data(code=code, year=year, quarterType=quarter_type)
        if rs.error_code != '0':
            return {}

        data = {}
        while rs.next():
            row = rs.get_row_data()
            data = {
                'code': row[0],
                'pubDate': row[1],
                'statDate': row[2],
                'dupontROE': float(row[3]) if row[3] else 0,
                'dupontNetProfitMargin': float(row[4]) if row[4] else 0,
                'dupontAssetTurnover': float(row[5]) if row[5] else 0,
                'dupontEquityMultiplier': float(row[6]) if row[6] else 0,
            }
            break

        return data

    def get_valuation_data(self, code: str, date: Optional[str] = None) -> Dict[str, float]:
        """获取估值数据（PE、PB等）"""
        if not self.login():
            return {}

        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        # 从最近的数据推算PE、PB
        year = datetime.now().year
        perf = self.get_performance_report(code, str(year), 4)

        if not perf:
            return {}

        k_data = self.get_recent_k_data(code, days=5)
        if k_data.empty:
            return {}

        last_close = k_data['close'].iloc[-1]
        eps = perf.get('eps', 0)
        bps = perf.get('bps', 0)

        pe = last_close / eps if eps > 0 else 0
        pb = last_close / bps if bps > 0 else 0

        return {
            'pe': pe,
            'pb': pb,
            'eps': eps,
            'bps': bps,
            'roe': perf.get('roe', 0),
            'last_close': last_close,
        }

    def get_sector_stocks(self, sector_code: str) -> List[str]:
        """获取板块成分股"""
        if not self.login():
            return []

        rs = bs.query_stock_industry(industry=sector_code)
        if rs.error_code != '0':
            return []

        codes = []
        while rs.next():
            row = rs.get_row_data()
            codes.append(row[0])

        return codes

    def get_dividend_data(self, code: str, year: str) -> Dict[str, Any]:
        """获取分红数据"""
        if not self.login():
            return {}

        rs = bs.query_dividend_data(code=code, year=year, yearType="report")
        if rs.error_code != '0':
            return {}

        data = {}
        while rs.next():
            row = rs.get_row_data()
            data = {
                'code': row[0],
                'dividendYear': row[1],
                'dividend': float(row[2]) if row[2] else 0,
                'dividendRatio': float(row[3]) if row[3] else 0,
            }
            break

        return data

    def __enter__(self):
        self.login()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.logout()


# 全局实例
_api_instance: Optional[BaoStockAPI] = None


def get_api() -> BaoStockAPI:
    """获取全局API实例"""
    global _api_instance
    if _api_instance is None:
        _api_instance = BaoStockAPI()
    return _api_instance