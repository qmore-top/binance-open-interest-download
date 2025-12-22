import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass
from enum import Enum
import json
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

class ErrorType(Enum):
    """错误类型枚举"""
    NETWORK_ERROR = "network_error"
    API_ERROR = "api_error"
    TIMEOUT_ERROR = "timeout_error"
    RATE_LIMIT_ERROR = "rate_limit_error"
    DATA_ERROR = "data_error"
    UNKNOWN_ERROR = "unknown_error"

@dataclass
class ErrorRecord:
    """错误记录"""
    symbol: str
    error_type: ErrorType
    error_message: str
    timestamp: datetime
    source: str = "realtime"  # realtime 或 history
    retry_count: int = 0
    fallback_used: bool = False
    resolved: bool = False

class ErrorHandler:
    """错误处理器"""

    def __init__(self, fallback_minutes: int = 5):
        """
        初始化错误处理器

        Args:
            fallback_minutes: 后备数据回溯分钟数
        """
        # 不再在此类中做重试，重试只保留在下载器内部
        self.max_retries = 0
        self.fallback_minutes = fallback_minutes
        self.error_history: List[ErrorRecord] = []
        self.error_stats_file = Path("data/error_statistics.json")
        self.lock = threading.Lock()  # 用于保护对统计文件的并发访问
        
        # 确保统计数据目录存在
        self.error_stats_file.parent.mkdir(parents=True, exist_ok=True)

    def classify_error(self, error: Exception) -> ErrorType:
        """
        分类错误类型

        Args:
            error: 异常对象

        Returns:
            错误类型
        """
        error_str = str(error).lower()

        if "timeout" in error_str or "time out" in error_str:
            return ErrorType.TIMEOUT_ERROR
        elif "rate limit" in error_str or "too many requests" in error_str:
            return ErrorType.RATE_LIMIT_ERROR
        elif "network" in error_str or "connection" in error_str:
            return ErrorType.NETWORK_ERROR
        elif "api" in error_str or "400" in error_str or "500" in error_str:
            return ErrorType.API_ERROR
        elif "data" in error_str or "json" in error_str:
            return ErrorType.DATA_ERROR
        else:
            return ErrorType.UNKNOWN_ERROR

    def should_retry(self, error_record: ErrorRecord) -> bool:
        """
        判断是否应该重试

        Args:
            error_record: 错误记录

        Returns:
            是否重试
        """
        if error_record.retry_count >= self.max_retries:
            return False

        # 对于某些错误类型，不重试
        if error_record.error_type in [ErrorType.DATA_ERROR]:
            return False

        return True

    def calculate_retry_delay(self, error_record: ErrorRecord) -> float:
        """
        计算重试延迟时间

        Args:
            error_record: 错误记录

        Returns:
            延迟秒数
        """
        base_delay = 1.0

        # 指数退避
        delay = base_delay * (2 ** error_record.retry_count)

        # 根据错误类型调整延迟
        if error_record.error_type == ErrorType.RATE_LIMIT_ERROR:
            delay *= 2  # API限制错误延迟更长
        elif error_record.error_type == ErrorType.TIMEOUT_ERROR:
            delay *= 1.5

        # 最大延迟不超过60秒
        return min(delay, 60.0)

    def handle_error_with_fallback(self,
                                   symbol: str,
                                   error: Exception,
                                   downloader: Any,
                                   storage: Any,
                                   source: str = "realtime") -> Optional[Dict]:
        """
        处理错误并尝试使用后备数据

        Args:
            symbol: 交易对符号
            error: 异常对象
            downloader: 下载器实例
            storage: 存储器实例

        Returns:
            后备数据或None
        """
        error_type = self.classify_error(error)
        error_record = ErrorRecord(
            symbol=symbol,
            error_type=error_type,
            error_message=str(error),
            timestamp=datetime.now(),
            source=source,
            retry_count=0
        )

        self.error_history.append(error_record)

        # 记录错误信息
        error_info = {
            "symbol": symbol,
            "error_type": error_type.value,
            "error_message": str(error),
            "timestamp": error_record.timestamp.isoformat(),
            "retry_count": error_record.retry_count
        }

        storage.save_error_log(symbol, error_info)
        
        # 更新错误统计
        self._update_error_statistics(error_record)

        logger.warning(f"下载失败 {symbol}: {error_type.value} - {error}")

        # 不再尝试历史数据兜底，直接返回失败
        return None

    def _update_error_statistics(self, error_record: ErrorRecord):
        """
        更新错误统计信息到JSON文件

        Args:
            error_record: 错误记录
        """
        with self.lock:  # 确保并发安全
            stats = self._load_error_statistics()
            
            # 更新统计信息
            stats["last_updated"] = datetime.now().isoformat()
            
            # 更新总计数
            stats["total_errors"] = stats.get("total_errors", 0) + 1
            
            # 按类型统计
            if "errors_by_type" not in stats:
                stats["errors_by_type"] = {}
            error_type = error_record.error_type.value
            stats["errors_by_type"][error_type] = stats["errors_by_type"].get(error_type, 0) + 1
            
            # 按交易对统计
            if "errors_by_symbol" not in stats:
                stats["errors_by_symbol"] = {}
            stats["errors_by_symbol"][error_record.symbol] = stats["errors_by_symbol"].get(error_record.symbol, 0) + 1
            
            # 记录详细错误列表，控制长度避免膨胀
            details = stats.get("details", [])
            details.append({
                "symbol": error_record.symbol,
                "error_type": error_type,
                "error_message": str(error_record.error_message)[:500],  # 截断避免过长
                "timestamp": error_record.timestamp.isoformat(),
                "retry_count": error_record.retry_count,
                "source": error_record.source
            })
            # 仅保留最新200条
            stats["details"] = details[-200:]
            
            # 按来源统计
            if "errors_by_source" not in stats:
                stats["errors_by_source"] = {}
            stats["errors_by_source"][error_record.source] = stats["errors_by_source"].get(error_record.source, 0) + 1
            
            # 统计后备使用情况
            if error_record.fallback_used:
                stats["fallback_usage"] = stats.get("fallback_usage", 0) + 1
                
            # 统计解决率
            if error_record.resolved:
                stats["resolved_errors"] = stats.get("resolved_errors", 0) + 1
            
            # 保存到文件
            try:
                with open(self.error_stats_file, 'w', encoding='utf-8') as f:
                    json.dump(stats, f, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.error(f"保存错误统计信息失败: {e}")

    def _load_error_statistics(self) -> Dict:
        """
        从文件加载错误统计信息

        Returns:
            错误统计字典
        """
        if not self.error_stats_file.exists():
            return {}
            
        try:
            with open(self.error_stats_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载错误统计信息失败: {e}")
            return {}

    def execute_with_retry(self,
                          operation: Callable,
                          symbol: str,
                          downloader: Any,
                          storage: Any,
                          *args,
                          source: str = "realtime",
                          **kwargs) -> Optional[Any]:
        """
        执行操作（不在此处重试，重试交给下载器内部完成）

        Args:
            operation: 要执行的操作函数
            symbol: 交易对符号
            downloader: 下载器实例
            storage: 存储器实例
            *args: 传递给操作函数的位置参数
            **kwargs: 传递给操作函数的关键字参数

        Returns:
            操作结果或None
        """
        try:
            result = operation(*args, **kwargs)

            # 返回 None 视为失败，走统一错误处理
            if result is None:
                raise RuntimeError("operation returned None")

            return result

        except Exception as e:
            error_record = ErrorRecord(
                symbol=symbol,
                error_type=self.classify_error(e),
                error_message=str(e),
                timestamp=datetime.now(),
                source=source,
                retry_count=0
            )
            self.error_history.append(error_record)
            logger.error(f"操作失败（不重试）{symbol}: {e}")
            return self.handle_error_with_fallback(symbol, e, downloader, storage, source=source)

    def get_error_statistics(self) -> Dict:
        """
        获取错误统计信息

        Returns:
            错误统计字典
        """
        if not self.error_history:
            return {"total_errors": 0}

        stats = {
            "total_errors": len(self.error_history),
            "errors_by_type": {},
            "errors_by_symbol": {},
            "fallback_usage": 0,
            "resolution_rate": 0
        }

        resolved_count = 0

        for error in self.error_history:
            # 按类型统计
            error_type = error.error_type.value
            stats["errors_by_type"][error_type] = stats["errors_by_type"].get(error_type, 0) + 1

            # 按交易对统计
            stats["errors_by_symbol"][error.symbol] = stats["errors_by_symbol"].get(error.symbol, 0) + 1

            # 统计后备使用
            if error.fallback_used:
                stats["fallback_usage"] += 1

            # 统计解决率
            if error.resolved:
                resolved_count += 1

        stats["resolution_rate"] = resolved_count / len(self.error_history) if self.error_history else 0

        return stats

    def clear_old_errors(self, days_to_keep: int = 7):
        """
        清理旧的错误记录

        Args:
            days_to_keep: 保留天数
        """
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        old_count = len(self.error_history)

        self.error_history = [
            error for error in self.error_history
            if error.timestamp > cutoff_date
        ]

        removed_count = old_count - len(self.error_history)
        if removed_count > 0:
            logger.info(f"清理了 {removed_count} 条旧错误记录")

    def export_error_report(self, filepath: str) -> bool:
        """
        导出错误报告

        Args:
            filepath: 报告文件路径

        Returns:
            导出是否成功
        """
        try:
            report = {
                "generated_at": datetime.now().isoformat(),
                "statistics": self.get_error_statistics(),
                "recent_errors": [
                    {
                        "symbol": error.symbol,
                        "error_type": error.error_type.value,
                        "error_message": error.error_message,
                        "timestamp": error.timestamp.isoformat(),
                        "retry_count": error.retry_count,
                        "fallback_used": error.fallback_used,
                        "resolved": error.resolved
                    }
                    for error in self.error_history[-100:]  # 最近100条
                ]
            }

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)

            logger.info(f"错误报告已导出: {filepath}")
            return True

        except Exception as e:
            logger.error(f"导出错误报告失败: {e}")
            return False