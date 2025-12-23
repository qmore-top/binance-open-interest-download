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

    def get_historical_open_interest(self, symbol: str, lookback_minutes: int = 5) -> Optional[Dict]:
        """
        获取指定交易对的历史未平仓合约数据（用于错误后的兜底）

        Args:
            symbol: 交易对符号
            lookback_minutes: 回溯分钟数

        Returns:
            最近一条历史未平仓数据，或None
        """
        # 仅支持5分钟粒度，回溯窗口用 lookback_minutes 控制
        end_time_ms = int(time.time() * 1000)
        start_time_ms = end_time_ms - max(lookback_minutes, self.OI_MIN_INTERVAL_MINUTES) * 60 * 1000

        history = self.get_oi_history(
            symbol=symbol,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            limit=1,
            interval_minutes=5
        )

        if not history:
            logger.warning(f"{symbol} 未获取到历史未平仓数据作为兜底")
            return None

        latest = history[-1]
        timestamp = latest.get("timestamp")
        if timestamp is None:
            logger.warning(f"{symbol} 历史数据缺少时间戳，跳过兜底")
            return None

        return {
            "symbol": latest.get("symbol", symbol.upper()),
            "openInterest": latest.get("sumOpenInterest"),
            "timestamp": timestamp,
            "datetime": datetime.fromtimestamp(timestamp / 1000).isoformat()
        }

    def validate_interval(self, interval_minutes: int, for_oi_history: bool = True) -> Dict[str, Any]:
        """
        验证时间间隔是否适合币安数据

        Args:
            interval_minutes: 时间间隔（分钟）
            for_oi_history: 是否用于OI历史数据（如果为True，则只检查OI历史API支持的间隔）

        Returns:
            验证结果字典
        """
        result = {
            "valid": True,
            "recommended_interval": 5,  # 总是推荐5分钟
            "warnings": [],
            "errors": []
        }

        # 对于OI历史数据，只支持5分钟间隔
        if for_oi_history:
            if interval_minutes != 5:
                result["valid"] = False
                result["errors"].append(f"币安OI历史数据只支持5分钟间隔，不支持{interval_minutes}分钟间隔")
                result["errors"].append("必须使用5分钟间隔获取历史数据")
        else:
            # 对于其他用途，使用标准间隔检查
            intervals_to_check = self.SUPPORTED_INTERVALS
            if interval_minutes not in intervals_to_check:
                result["valid"] = False
                result["errors"].append(f"不支持的时间间隔: {interval_minutes}分钟")
                closest_interval = min(intervals_to_check.keys(),
                                     key=lambda x: abs(x - interval_minutes))
                result["recommended_interval"] = closest_interval
                result["errors"].append(f"建议使用: {closest_interval}分钟间隔")

        return result

    def get_recommended_interval(self, requested_interval: int) -> int:
        """
        获取推荐的时间间隔

        Args:
            requested_interval: 请求的间隔

        Returns:
            推荐的间隔
        """
        # 如果请求的间隔有效，直接返回
        if requested_interval in self.SUPPORTED_INTERVALS:
            return requested_interval

        # 否则返回最接近的可用间隔
        return min(self.SUPPORTED_INTERVALS.keys(),
                  key=lambda x: abs(x - requested_interval))

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

            # 添加时间戳 - 如果提供自定义时间戳则使用，否则使用当前时间
            if custom_timestamp is not None:
                data["timestamp"] = custom_timestamp
                data["datetime"] = datetime.fromtimestamp(custom_timestamp / 1000).isoformat()
            else:
                data["timestamp"] = int(time.time() * 1000)
                data["datetime"] = datetime.now().isoformat()

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
                       start_time_ms: int,
                       end_time_ms: int,
                       limit: int = 1000,
                       interval_minutes: int = 5) -> Optional[List[Dict[str, Any]]]:
        """
        获取5分钟历史未平仓数据（受币安限制：最多1000条，时间范围仅30天内）

        Args:
            symbol: 交易对
            start_time_ms: 起始时间戳（毫秒）
            end_time_ms: 结束时间戳（毫秒）
            limit: 每次拉取条数，最大1000
            interval_minutes: 时间间隔，必须为5

        Returns:
            历史记录列表或None
        """
        # 币安官方接口仅支持5m
        if interval_minutes != 5:
            logger.error("OI历史数据仅支持5分钟间隔")
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
        return data