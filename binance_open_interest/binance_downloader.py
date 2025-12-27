"""
Binance数据下载器模块
负责从币安API下载Open Interest数据和历史数据
"""

import requests
import time
import logging
from typing import Dict, List, Optional, Tuple, Any, Callable
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)

class BinanceDownloader:
    """币安数据下载器"""

    BASE_URL = "https://fapi.binance.com"

    # 币安OI历史数据API实际支持的时间间隔（根据官方文档）
    # https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics
    OI_HISTORY_INTERVALS = {
        5: "5m",      # 5分钟 - 唯一支持的间隔（最可靠）
    }

    # 兼容性：包含所有可能的间隔，用于K线等其他API
    SUPPORTED_INTERVALS = {
        1: "1m", 3: "3m", 5: "5m", 15: "15m", 30: "30m",
        60: "1h", 120: "2h", 240: "4h", 360: "6h", 480: "8h",
        720: "12h", 1440: "1d"
    }

    # OI历史数据最小间隔（5分钟）
    OI_MIN_INTERVAL_MINUTES = 5

    def __init__(self,
                 timeout: int = 5,
                 max_retries: int = 3,
                 proxy: Optional[Dict[str, str]] = None,
                 shutdown_checker: Optional[Callable[[], bool]] = None):
        """
        初始化下载器

        Args:
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
            proxy: 代理服务器配置字典，例如：
                   {"http": "http://proxy.example.com:8080", "https": "http://proxy.example.com:8080"}
                   或 {"http": "socks5://proxy.example.com:1080", "https": "socks5://proxy.example.com:1080"}
            shutdown_checker: 可选的关闭检查函数，返回 True 时停止重试/等待
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.proxy = proxy
        self.session = requests.Session()
        self.shutdown_checker = shutdown_checker

        # 配置代理
        if proxy:
            self.session.proxies.update(proxy)
            logger.info(f"已配置代理服务器: {proxy}")
        else:
            logger.info("未配置代理服务器，使用直连模式")

    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """
        发送HTTP请求到币安API

        Args:
            endpoint: API端点
            params: 请求参数

        Returns:
            API响应数据或None（失败时）
        """
        url = f"{self.BASE_URL}{endpoint}"
        last_error = None

        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()

                data = response.json()
                logger.debug(f"成功获取数据: {endpoint}")
                return data

            except requests.exceptions.RequestException as e:
                # 尽量带上响应正文，便于错误统计记录具体原因；并在4xx时直接停止重试（1121等无效交易对不再重试）
                status = getattr(getattr(e, "response", None), "status_code", None)
                resp_text = ""
                if getattr(e, "response", None) is not None:
                    try:
                        resp_text = e.response.text
                    except Exception:
                        resp_text = ""

                # 解析币安错误码
                binance_code = None
                if resp_text:
                    try:
                        parsed = json.loads(resp_text)
                        binance_code = parsed.get("code")
                    except Exception:
                        binance_code = None

                # 对于客户端错误/已知无效符号，直接抛出，不再重试
                if status is not None and 400 <= status < 500:
                    logger.error(f"客户端错误，无需重试: {endpoint} - status={status}, code={binance_code}, resp={resp_text}")
                    raise RuntimeError(f"{endpoint} 客户端错误 {status}, code={binance_code}, resp={resp_text}") from e
                if binance_code == 1121:
                    logger.error(f"无效交易对，无需重试: {endpoint} - code=1121, resp={resp_text}")
                    raise RuntimeError(f"{endpoint} 无效交易对(1121), resp={resp_text}") from e

                last_error = e
                logger.warning(f"请求失败 (尝试 {attempt + 1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    # 如果外部请求了关闭，则不再等待重试
                    if self.shutdown_checker and self.shutdown_checker():
                        raise RuntimeError("收到关闭信号，终止重试") from e
                    time.sleep(2 ** attempt)  # 指数退避
                else:
                    logger.error(f"请求最终失败: {endpoint} - {e} - resp: {resp_text}")
                    raise RuntimeError(f"{endpoint} 在重试 {self.max_retries} 次后仍失败: {e}; resp={resp_text}") from e
            except json.JSONDecodeError as e:
                logger.error(f"JSON解析失败: {e}")
                raise RuntimeError(f"{endpoint} JSON 解析失败: {e}") from e

        return None



    def get_open_interest(self, symbol: str, custom_timestamp: Optional[int] = None) -> Optional[Dict]:
        """
        获取指定交易对的未平仓合约数量

        Args:
            symbol: 交易对符号，如"BTCUSDT"
            custom_timestamp: 自定义时间戳（毫秒），如果为None则使用当前时间

        Returns:
            包含未平仓合约数据的字典或None
        """
        endpoint = "/fapi/v1/openInterest"
        params = {"symbol": symbol.upper()}

        data = self._make_request(endpoint, params)
        if data:
            # 尝试获取标记价用于计算名义价值
            try:
                price = self.get_mark_price(symbol)
                if price is not None:
                    oi_float = float(data.get("openInterest", 0))
                    price_float = float(price)
                    data["sumOpenInterestValue"] = oi_float * price_float
                else:
                    logger.warning(f"{symbol} 获取标记价返回空，sumOpenInterestValue 留空")
                    data["sumOpenInterestValue"] = None
            except Exception as e:
                logger.warning(f"计算名义价值失败 {symbol}: {e}")
                data["sumOpenInterestValue"] = None

            # 添加时间戳 - 如果提供自定义时间戳则使用，否则使用当前UTC时间
            if custom_timestamp is not None:
                data["timestamp"] = custom_timestamp
                data["datetime"] = datetime.utcfromtimestamp(custom_timestamp / 1000).isoformat() + "Z"
            else:
                data["timestamp"] = int(time.time() * 1000)
                data["datetime"] = datetime.utcnow().isoformat() + "Z"

            logger.info(f"成功获取 {symbol} 未平仓合约: {data.get('openInterest', 'N/A')} (时间戳: {data['timestamp']})")
            return data

        return None

    def get_mark_price(self, symbol: str) -> Optional[float]:
        """
        获取最新标记价格
        """
        endpoint = "/fapi/v1/premiumIndex"
        params = {"symbol": symbol.upper()}
        data = self._make_request(endpoint, params)
        if not data:
            return None
        try:
            return float(data.get("markPrice"))
        except Exception:
            return None

    def get_multiple_symbols_oi(self, symbols: List[str]) -> Dict[str, Optional[Dict]]:
        """
        批量获取多个交易对的未平仓合约数据

        Args:
            symbols: 交易对符号列表

        Returns:
            交易对到数据的映射字典
        """
        results = {}
        total_symbols = len(symbols)

        logger.info(f"开始批量下载 {total_symbols} 个交易对的未平仓合约数据")

        for i, symbol in enumerate(symbols, 1):
            logger.info(f"处理 {i}/{total_symbols}: {symbol}")
            data = self.get_open_interest(symbol)
            results[symbol] = data

            # 添加小延迟避免触发API限制
            if i < total_symbols:
                time.sleep(0.1)

        success_count = sum(1 for data in results.values() if data is not None)
        logger.info(f"批量下载完成: {success_count}/{total_symbols} 成功")

        return results

    def get_server_time(self) -> Optional[int]:
        """
        获取币安服务器时间

        Returns:
            服务器时间戳（毫秒）或None
        """
        endpoint = "/fapi/v1/time"
        data = self._make_request(endpoint)

        if data:
            return data.get("serverTime")

        return None

    def get_oi_history(self,
                       symbol: str,
                       date_str: str,
                       limit: int = 1000,
                       start_timestamp: Optional[int] = None) -> Optional[List[Dict[str, Any]]]:
        """
        获取指定日期的5分钟历史未平仓数据（按天下载，受币安限制：最多1000条）

        Args:
            symbol: 交易对
            date_str: 日期字符串，格式为 "YYYY-MM-DD"（UTC日期）
            limit: 每次拉取条数，最大1000
            start_timestamp: 开始时间戳（毫秒），如果提供则从此时间开始下载，否则从当天开始

        Returns:
            历史记录列表或None
        """
        try:
            from datetime import datetime, timezone

            if start_timestamp:
                # 使用提供的开始时间戳
                start_time_ms = start_timestamp
                # 结束时间是当天23:59:59.999
                date_obj = datetime.utcfromtimestamp(start_timestamp / 1000).replace(hour=23, minute=59, second=59, microsecond=999999)
                end_time_ms = int(date_obj.timestamp() * 1000)
            else:
                # 解析日期，创建UTC时间范围
                # 创建UTC日期对象（naive datetime + UTC时区）
                date_obj = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

                # 当天的开始时间（UTC 00:00:00）
                start_time_ms = int(date_obj.timestamp() * 1000)

                # 当天的结束时间（UTC 23:59:59.999）
                end_time_ms = start_time_ms + (24 * 60 * 60 * 1000) - 1

        except ValueError as e:
            logger.error(f"无效的日期格式 {date_str}: {e}")
            return None

        params = {
            "symbol": symbol.upper(),
            "period": "5m",
            "limit": min(limit, 1000),
            "startTime": start_time_ms,
            "endTime": end_time_ms
        }

        endpoint = "/futures/data/openInterestHist"
        data = self._make_request(endpoint, params)
        if data is None:
            return None

        # 接口返回列表，每项包含sumOpenInterest等字段
        logger.info(f"获取 {symbol} {date_str} 历史数据: {len(data)} 条记录")
        return data