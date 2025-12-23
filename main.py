"""
Binance Open Interest Downloader
Download and manage Binance futures open interest data
"""

import os
import argparse
import sys
import signal
import time
import json
import logging
import threading
import concurrent.futures
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any

import schedule

from binance_open_interest import (
    BinanceDownloader,
    DataStorage,
    ErrorHandler,
    ConfigManager
)

# 临时配置日志（将在配置加载后重新配置）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# 默认的热门交易对
DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "XRPUSDT",
    "SOLUSDT", "DOTUSDT", "DOGEUSDT", "AVAXUSDT", "LTCUSDT",
    "BCHUSDT", "LINKUSDT", "UNIUSDT", "ALGOUSDT", "VETUSDT"
]
def get_proxy_config(http_proxy: Optional[str] = None,
                     https_proxy: Optional[str] = None,
                     socks_proxy: Optional[str] = None) -> Optional[Dict[str, str]]:
    """
    获取代理配置

    Args:
        http_proxy: HTTP代理地址
        https_proxy: HTTPS代理地址
        socks_proxy: SOCKS代理地址

    Returns:
        代理配置字典或None
    """
    import os

    proxy_config = {}

    # 从环境变量获取
    if not http_proxy:
        http_proxy = os.getenv('HTTP_PROXY') or os.getenv('http_proxy')
    if not https_proxy:
        https_proxy = os.getenv('HTTPS_PROXY') or os.getenv('https_proxy')
    if not socks_proxy:
        socks_proxy = os.getenv('SOCKS_PROXY') or os.getenv('socks_proxy') or os.getenv('ALL_PROXY')

    # 如果指定了SOCKS代理，则同时用于HTTP和HTTPS
    if socks_proxy:
        proxy_config['http'] = socks_proxy
        proxy_config['https'] = socks_proxy
        logger.info(f"使用SOCKS代理: {socks_proxy}")
    else:
        # 使用HTTP/HTTPS代理
        if http_proxy:
            proxy_config['http'] = http_proxy
            logger.info(f"使用HTTP代理: {http_proxy}")
        if https_proxy:
            proxy_config['https'] = https_proxy
            logger.info(f"使用HTTPS代理: {https_proxy}")

        return proxy_config if proxy_config else None

class BinanceOIDownloader:
    """Binance Open Interest Downloader main class"""

    def __init__(self, config_manager: ConfigManager, proxy_config: Optional[Dict[str, str]] = None):
        """
        Initialize the downloader

        Args:
            config_manager: Configuration manager instance
            proxy_config: Proxy server configuration dictionary
        """
        self.config_manager = config_manager
        self.data_dir = config_manager.get_data_dir()
        # 传入 shutdown_checker，收到关闭信号时可打断重试/等待
        self.downloader = BinanceDownloader(
            proxy=proxy_config,
            shutdown_checker=lambda: self.shutdown_requested
        )
        self.storage = DataStorage(base_dir=self.data_dir)
        self.error_handler = ErrorHandler()

        # 运行状态管理
        self.shutdown_requested = False

        # 设置信号处理器
        self._setup_signal_handlers()

        logger.info("Binance 未平仓数据下载器已初始化")

    def start_oi_history_worker(self, symbols: List[str]):
        """
        启动5分钟历史数据下载线程

        Args:
            symbols: 交易对列表
        """
        thread = threading.Thread(
            target=self._download_oi_history_for_symbols,
            args=(symbols,),
            daemon=True
        )
        thread.start()
        logger.info(f"已启动5分钟历史数据线程，交易对数: {len(symbols)}")

    def _download_oi_history_for_symbols(self, symbols: List[str]):
        """后台线程：为多个交易对下载5分钟历史数据（持续循环，默认每5分钟巡检）"""
        interval_ms = 5 * 60 * 1000
        batch_span_ms = interval_ms * 1000  # 1000条上限
        buffer_ms = 60 * 60 * 1000
        max_lookback_ms = 30 * 24 * 60 * 60 * 1000

        try:
            while not self.shutdown_requested:
                server_time_ms = self.downloader.get_server_time()
                if not server_time_ms:
                    logger.warning("无法获取服务器时间，跳过本轮5m历史下载")
                    self.error_handler.handle_error_with_fallback(
                        symbol="ALL",
                        error=RuntimeError("server time unavailable for history"),
                        downloader=self.downloader,
                        storage=self.storage,
                        source="history"
                    )
                    # 等待下轮
                    time.sleep(300)
                    continue

                earliest_allowed = server_time_ms - max_lookback_ms + buffer_ms
                latest_allowed = server_time_ms - buffer_ms

                for symbol in symbols:
                    if self.shutdown_requested:
                        break

                    try:
                        last_ts = self.storage.get_last_5m_timestamp(symbol)
                        start_ms = last_ts + interval_ms if last_ts else earliest_allowed
                        start_ms = max(start_ms, earliest_allowed)

                        # 对齐到5分钟边界
                        remainder = start_ms % interval_ms
                        if remainder:
                            start_ms += (interval_ms - remainder)

                        logger.info(f"5m历史下载开始 {symbol}: start_ms={start_ms}, latest_allowed={latest_allowed}")

                        current_start = start_ms
                        while current_start <= latest_allowed and not self.shutdown_requested:
                            end_ms = min(current_start + batch_span_ms, latest_allowed)
                            data = self.downloader.get_oi_history(
                                symbol,
                                start_time_ms=current_start,
                                end_time_ms=end_ms,
                                limit=1000,
                                interval_minutes=5
                            )
                            if not data:
                                logger.warning(f"{symbol} 5m历史下载返回空，终止该交易对")
                                self.error_handler.handle_error_with_fallback(
                                    symbol=symbol,
                                    error=RuntimeError("history fetch returned empty"),
                                    downloader=self.downloader,
                                    storage=self.storage,
                                    source="history"
                                )
                                break

                            # 保存
                            saved = self.storage.save_oi_history_batch(symbol, data)
                            if not saved:
                                logger.error(f"{symbol} 5m历史数据保存失败，终止该交易对")
                                self.error_handler.handle_error_with_fallback(
                                    symbol=symbol,
                                    error=RuntimeError("history save failed"),
                                    downloader=self.downloader,
                                    storage=self.storage,
                                    source="history"
                                )
                                break

                            last_entry_ts = int(data[-1].get("timestamp", current_start))
                            # 防止卡住：返回数据未前进，通常表示已到达可下载的最新时间
                            if last_entry_ts <= current_start:
                                break

                            current_start = last_entry_ts + interval_ms

                            # 轻微节流
                            time.sleep(0.1)

                        logger.info(f"5m历史下载完成 {symbol}")
                    except Exception as e:
                        logger.error(f"5m历史下载异常 {symbol}: {e}")
                        self.error_handler.handle_error_with_fallback(
                            symbol=symbol,
                            error=e,
                            downloader=self.downloader,
                            storage=self.storage,
                            source="history"
                        )
                        continue

                # 本轮完成，等下一轮（5分钟），可随时通过 shutdown 请求终止
                sleep_seconds = 300
                for _ in range(sleep_seconds):
                    if self.shutdown_requested:
                        break
                    time.sleep(1)

        except Exception as e:
            logger.error(f"5m历史下载线程异常: {e}")
            self.error_handler.handle_error_with_fallback(
                symbol="ALL",
                error=e,
                downloader=self.downloader,
                storage=self.storage,
                source="history"
            )

    def _setup_signal_handlers(self):
        """设置信号处理器用于优雅关闭"""
        def signal_handler(signum, frame):
            """信号处理函数"""
            logger.info(f"Received signal {signum}, initiating graceful shutdown...")
            self.shutdown_requested = True
            try:
                import schedule
                schedule.clear()
            except Exception:
                pass
            # 直接抛出中断，加速当前阻塞流程的退出
            raise KeyboardInterrupt()

        # 注册信号处理器
        signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
        signal.signal(signal.SIGTERM, signal_handler)  # kill命令

    def _scan_and_fill_gaps(self, symbols: List[str], interval_minutes: int = 5):
        """
        扫描文件系统，查找缺失的数据点并补全

        Args:
            symbols: 交易对列表
            interval_minutes: 时间间隔（分钟）
        """
        from datetime import datetime, timedelta
        import os

        logger.info(f"开始扫描文件系统并补全缺失数据")

        # 获取当前时间和任务开始时间（默认回溯24小时）
        now = datetime.now()
        start_time = datetime.fromtimestamp(time.time() - 3600*24)

        # 计算应该有的数据点时间戳（每5分钟一个点）
        expected_timestamps = []
        current_time = start_time.replace(second=0, microsecond=0)

        # 对齐到5分钟间隔
        minutes_offset = current_time.minute % 5
        if minutes_offset != 0:
            current_time = current_time - timedelta(minutes=minutes_offset)

        while current_time <= now:
            expected_timestamps.append(int(current_time.timestamp() * 1000))
            current_time += timedelta(minutes=interval_minutes)

        logger.info(f"期望的数据点数量: {len(expected_timestamps)}")

        # 为每个交易对检查缺失的数据
        for symbol in symbols:
            if self.shutdown_requested:
                logger.info("补全过程中收到关闭请求")
                break

            logger.info(f"检查 {symbol} 的缺失数据...")

            # 获取已有的数据文件
            existing_timestamps = set()
            symbol_dir = os.path.join(self.data_dir, symbol)

            if os.path.exists(symbol_dir):
                for filename in os.listdir(symbol_dir):
                    if filename.endswith('.json'):
                        try:
                            # 从文件名提取时间戳
                            timestamp_str = filename.replace('.json', '').split('_')[-1]
                            timestamp = int(timestamp_str)
                            existing_timestamps.add(timestamp)
                        except (ValueError, IndexError):
                            continue

            # 找出缺失的时间戳
            missing_timestamps = [ts for ts in expected_timestamps if ts not in existing_timestamps]

            if missing_timestamps:
                logger.info(f"{symbol} 缺失 {len(missing_timestamps)} 个数据点，开始补全...")

                for i, timestamp in enumerate(missing_timestamps, 1):
                    if self.shutdown_requested:
                        break

                    logger.info(f"补全 {symbol} - {i}/{len(missing_timestamps)}: {datetime.fromtimestamp(timestamp/1000)}")
                    try:
                        self.download_single_symbol(symbol, timestamp)
                        time.sleep(0.1)  # 小延迟避免请求过于频繁
                    except Exception as e:
                        logger.error(f"补全 {symbol} 失败: {e}")
                        continue
            else:
                logger.info(f"{symbol} 数据完整，无需补全")

        logger.info(f"文件补全任务完成")

    def export_data_to_csv(self) -> bool:
        """
        导出数据到CSV文件

        Returns:
            是否导出成功
        """
        try:
            import csv
            import os
            from pathlib import Path

            export_dir = Path(self.data_dir) / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)

            export_file = export_dir / f"open_interest_export_{int(time.time())}.csv"

            logger.info(f"开始导出数据到: {export_file}")

            # 收集所有数据
            all_data = []

            # 遍历所有交易对目录
            data_dir = Path(self.data_dir)
            for symbol_dir in data_dir.iterdir():
                if symbol_dir.is_dir() and not symbol_dir.name.startswith('.'):
                    symbol = symbol_dir.name

                    # 遍历该交易对的所有数据文件
                    for data_file in symbol_dir.glob("*.json"):
                        try:
                            with open(data_file, 'r', encoding='utf-8') as f:
                                data = json.load(f)

                            # 提取数据
                            timestamp = data.get('timestamp', 0)
                            open_interest = data.get('openInterest', 0)
                            symbol_count = data.get('countTop', 0)
                            count_long_short_ratio = data.get('countlongshortRatio', 0)
                            count_long_short_ratio_timestamp = data.get('countlongshortRatioTimestamp', 0)

                            all_data.append({
                                'symbol': symbol,
                                'timestamp': timestamp,
                                'datetime': datetime.fromtimestamp(timestamp / 1000).isoformat(),
                                'open_interest': open_interest,
                                'symbol_count': symbol_count,
                                'count_long_short_ratio': count_long_short_ratio,
                                'count_long_short_ratio_timestamp': count_long_short_ratio_timestamp
                            })

                        except Exception as e:
                            logger.warning(f"读取文件失败 {data_file}: {e}")
                            continue

            # 按时间戳排序
            all_data.sort(key=lambda x: x['timestamp'])

            # 写入CSV
            if all_data:
                with open(export_file, 'w', newline='', encoding='utf-8') as f:
                    fieldnames = ['symbol', 'timestamp', 'datetime', 'open_interest', 'symbol_count',
                                'count_long_short_ratio', 'count_long_short_ratio_timestamp']
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(all_data)

                logger.info(f"数据导出完成，共导出 {len(all_data)} 条记录到 {export_file}")
                return True
            else:
                logger.warning("没有找到数据进行导出")
                return False

        except Exception as e:
            logger.error(f"导出数据失败: {e}")
            return False

    def download_single_symbol(self, symbol: str, custom_timestamp: Optional[int] = None) -> bool:
        """
        下载单个交易对

        Args:
            symbol: 交易对
            custom_timestamp: 自定义时间戳（毫秒），为空则使用当前时间

        Returns:
            是否成功
        """
        logger.info(f"开始下载未平仓数据: {symbol}")

        # 使用错误处理器执行下载
        result = self.error_handler.execute_with_retry(
            self.downloader.get_open_interest,
            symbol,
            self.downloader,
            self.storage,
            symbol,
            custom_timestamp,
            source="realtime"
        )

        # 下载返回 None 视为失败，抛出异常以便错误处理器记录统计
        if result is None:
            raise RuntimeError(f"open interest fetch returned None for {symbol}")

        # 保存数据到文件
        file_saved = self.storage.save_open_interest_data(symbol, result)

        logger.info(f"下载成功 {symbol}: 未平仓量 = {result.get('openInterest', 'N/A')}")
        return True

    def download_with_minute_timestamp(self, symbol: str, use_integer_minute: bool = True) -> bool:
        """
        Download data using timestamp from previous integer minute

        Args:
            symbol: Trading pair symbol
            use_integer_minute: Whether to use integer minute timestamp

        Returns:
            Whether download was successful
        """
        if use_integer_minute:
            # 计算当前整数分钟的时间戳（毫秒）
            now = datetime.now()
            current_minute = now.replace(second=0, microsecond=0)
            custom_timestamp = int(current_minute.timestamp() * 1000)
            logger.info(f"使用整数分钟时间戳: {custom_timestamp} ({current_minute.isoformat()})")
        else:
            custom_timestamp = None
            logger.info("使用当前时间戳")

        return self.download_single_symbol(symbol, custom_timestamp)

    def download_multiple_symbols(self, symbols: List[str]) -> Dict[str, bool]:
        """
        下载多个交易对

        Args:
            symbols: 交易对列表
            resume_task_id: 恢复任务ID（可选）

        Returns:
            每个交易对的下载结果字典
        """
        logger.info(f"开始批量下载 {len(symbols)} 个交易对")

        start_time = time.time()
        # 使用同一个整数分钟时间戳，避免串行延迟导致数据时间不一致
        batch_timestamp = int(datetime.now().replace(second=0, microsecond=0).timestamp() * 1000)
        logger.info(f"批量下载使用统一整数分钟时间戳: {batch_timestamp} ({datetime.fromtimestamp(batch_timestamp/1000).isoformat()})")

        results: Dict[str, bool] = {}
        processed_count = 0

        # 线程并发下载，避免串行延迟
        max_workers = self._get_worker_count(len(symbols))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_symbol = {
                executor.submit(self.download_single_symbol, symbol, batch_timestamp): symbol
                for symbol in symbols
            }

            for future in concurrent.futures.as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                if self.shutdown_requested:
                    logger.info("Shutdown requested during batch processing")
                    break
                try:
                    success = future.result()
                except Exception as e:
                    logger.error(f"下载失败 {symbol}: {e}")
                    success = False
                results[symbol] = success
                processed_count += 1
                if self.shutdown_requested:
                    logger.info("Shutdown requested during batch processing")
                    break

        # 计算统计信息
        duration = time.time() - start_time
        success_count = sum(1 for success in results.values() if success)

        if self.shutdown_requested:
            logger.info(f"批量下载被中断: {processed_count}/{len(symbols)} 已处理，成功 {success_count}")
        else:
            logger.info(f"批量下载完成: 成功 {success_count}/{len(symbols)}，耗时 {duration:.2f} 秒")


        # 保存汇总信息到文件
        batch_info = {
            "duration": duration,
            "timestamp": datetime.now().isoformat(),
            "interrupted": self.shutdown_requested,
            "processed_count": processed_count
        }
        self.storage.save_batch_results(results, batch_info)

        return results


    def show_statistics(self):
        """Display statistics"""
        logger.info("=== Data Storage Statistics ===")

        # 存储统计
        storage_stats = self.storage.get_storage_stats()
        if storage_stats:
            print(f"存储统计:")
            print(f"总文件数: {storage_stats.get('total_files', 0)}")
            print(f"总大小: {storage_stats.get('total_size_mb', 0):.2f} MB")

            directories = storage_stats.get('directories', {})
            if directories:
                print("按目录统计:")
                for dir_name, dir_stats in directories.items():
                    print(f"  {dir_name}: {dir_stats.get('file_count', 0)} 文件, {dir_stats.get('size_mb', 0):.2f} MB")
        else:
            print("暂无存储统计信息")

    def _get_worker_count(self, symbol_count: int) -> int:
        """
        获取并发工作线程数（可配置，默认 CPU*2 上限32）
        """
        # 优先环境变量控制
        env_val = os.getenv("OI_MAX_WORKERS")
        if env_val:
            try:
                workers = int(env_val)
                if workers > 0:
                    return min(workers, symbol_count)
            except ValueError:
                pass

        cpu_cnt = os.cpu_count() or 4
        workers = min(max(1, cpu_cnt * 2), 32, symbol_count)
        return workers

    def cleanup_old_data(self, days: int = 30):
        """
        Clean up old data

        Args:
            days: Number of days to retain
        """
        logger.info(f"Starting cleanup of data older than {days} days")

        # 清理文件
        self.storage.cleanup_old_files(days)

        # 清理错误处理器记录
        self.error_handler.clear_old_errors(days)

        logger.info("Data cleanup completed")

    def start_scheduled_download(self, symbols: List[str], interval_minutes: int = 1):
        """
        Start scheduled download

        Args:
            symbols: List of symbols to download
            interval_minutes: Download interval in minutes
        """
        logger.info("开始定时下载任务")
        execution_count = 0

        def download_job():
            nonlocal execution_count

            if self.shutdown_requested:
                logger.info("Shutdown requested, stopping scheduled download")
                return

            execution_count += 1
            current_time = datetime.now()
            logger.info(f"Starting scheduled download task #{execution_count} - {len(symbols)} symbols")

            success_count = 0
            for i, symbol in enumerate(symbols, 1):
                if self.shutdown_requested:
                    logger.info("Shutdown requested during symbol processing")
                    break

                try:
                    logger.info(f"Processing {i}/{len(symbols)}: {symbol}")
                    success = self.download_with_minute_timestamp(symbol, use_integer_minute=True)
                    if success:
                        success_count += 1
                    else:
                        logger.warning(f"Scheduled download failed for {symbol}")
                except Exception as e:
                    logger.error(f"Error during scheduled download of {symbol}: {e}")

            logger.info(f"Scheduled download task #{execution_count} completed: {success_count}/{len(symbols)} successful")

        # 等待到下一个整数分钟
        def wait_for_next_minute():
            now = datetime.now()
            next_minute = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
            sleep_time = (next_minute - now).total_seconds()
            logger.info(f"等待 {sleep_time:.1f} 秒到下一个整数分钟 {next_minute.strftime('%H:%M')}")
            time.sleep(sleep_time)
        
        # 立即执行一次
        download_job()
        
        # 开始调度循环
        try:
            while not self.shutdown_requested:
                wait_for_next_minute()
                download_job()
        except KeyboardInterrupt:
            logger.info("Scheduled download interrupted by user")
        finally:
            logger.info("Scheduled download stopped")

    def download_continuous(self, symbols: List[str], duration_hours: Optional[float] = None):
        """
        Download continuously for specified duration

        Args:
            symbols: List of symbols to download
            duration_hours: Duration in hours, infinite if None
        """
        start_time = time.time()
        download_count = 0
        logger.info(f"Starting continuous download, symbols: {symbols}")
        if duration_hours:
            logger.info(f"Duration: {duration_hours} hours")
        else:
            logger.info("Continuous mode, press Ctrl+C to stop gracefully")

        try:
            while not self.shutdown_requested:
                # 检查是否超过持续时长
                if duration_hours and (time.time() - start_time) >= (duration_hours * 3600):
                    logger.info(f"Reached specified duration {duration_hours} hours, stopping download")
                    break

                download_count += 1
                current_time = datetime.now()
                logger.info(f"=== Download #{download_count} ===")

                success_count = 0
                for symbol in symbols:
                    if self.shutdown_requested:
                        break

                    success = self.download_with_minute_timestamp(symbol)
                    if success:
                        success_count += 1
                    else:
                        logger.warning(f"Download #{download_count} failed for {symbol}")

                logger.info(f"Download #{download_count} completed: {success_count}/{len(symbols)} successful")

                if not self.shutdown_requested:
                    # 等待到下一个整数分钟
                    now = datetime.now()
                    seconds_to_next_minute = 60 - now.second
                    logger.info(f"Waiting {seconds_to_next_minute} seconds until next integer minute...")

                    # 分段等待，支持中断
                    wait_start = time.time()
                    while time.time() - wait_start < seconds_to_next_minute and not self.shutdown_requested:
                        time.sleep(min(1, seconds_to_next_minute - (time.time() - wait_start)))

        except KeyboardInterrupt:
            logger.info("Continuous download interrupted by user")

        total_duration = time.time() - start_time

        if self.shutdown_requested:
            logger.info(f"Continuous download interrupted after {download_count} downloads, total time: {total_duration:.1f} seconds")
        else:
            logger.info(f"Continuous download finished, {download_count} downloads completed, total time: {total_duration:.1f} seconds")
            self._complete_task(task_id)

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Binance Open Interest Downloader - Download futures open interest data")
    parser.add_argument("--symbols", "-S", nargs="+", help="指定交易对符号（单个或多个，用空格分隔）")
    parser.add_argument("--stats", action="store_true", help="显示统计信息")
    parser.add_argument("--cleanup", type=int, metavar="DAYS", help="清理指定天数前的旧数据")
    parser.add_argument("--hours", "-c", type=float, metavar="HOURS", help="持续下载指定小时数")
    parser.add_argument("--history-only", action="store_true", help="仅下载5分钟历史数据，不进行实时下载")

    args = parser.parse_args()

    # 加载配置（固定使用默认路径）
    config_path = "config/config.json"

    config_manager = ConfigManager(config_path)

    # 验证配置
    config_errors = config_manager.validate_config()
    if config_errors:
        print("配置文件错误:")
        for error in config_errors:
            print(f"  - {error}")
        sys.exit(1)

    # 获取代理配置（使用环境变量）
    proxy_config = get_proxy_config()

    # 获取存储配置
    data_dir = config_manager.get_data_dir()

    # 重新配置日志，使用配置的数据目录
    if config_manager.get_logging_config().get("file_enabled", True):
        from pathlib import Path
        log_dir = Path(data_dir) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "binance_oi_downloader.log"

        # 添加文件处理器
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

        # 获取根日志器并添加文件处理器
        root_logger = logging.getLogger()
        root_logger.addHandler(file_handler)

        logger.info(f"日志文件: {log_file}")

    # Initialize downloader
    downloader = BinanceOIDownloader(config_manager=config_manager, proxy_config=proxy_config)

    # 确定要下载的交易对
    target_symbols = []
    if args.symbols:
        target_symbols = args.symbols
    else:
        # 使用配置文件中的交易对
        target_symbols = config_manager.get_symbols()
        if not target_symbols:
            print("错误: 未指定交易对且配置文件中也没有交易对设置")
            sys.exit(1)

    # 启动5分钟历史数据后台线程
    downloader.start_oi_history_worker(target_symbols)

    # 如果仅需历史数据，启动后直接返回，不做实时下载
    if args.history_only:
        logger.info("仅下载5分钟历史数据，不执行实时下载")
        return

    try:
        if args.stats:
            # 显示统计信息
            downloader.show_statistics()

        elif args.cleanup:
            # 清理旧数据
            downloader.cleanup_old_data(args.cleanup)

        elif not any([args.stats, args.cleanup, args.hours]):
            # 定时下载模式（每1分钟拉取一次）
            interval_minutes = 1
            print(f"启动定时模式，每 {interval_minutes} 分钟拉取: {target_symbols}")
            print(f"使用的配置文件: {config_manager.get_config_path()}")
            print(config_manager.get_config_summary())
            logger.info("按整数分钟调度")

            def scheduled_job():
                if downloader.shutdown_requested:
                    return schedule.CancelJob
                try:
                    logger.info("开始执行定时任务")
                    downloader.download_multiple_symbols(target_symbols)
                    logger.info("定时任务执行完成")
                except Exception as e:
                    logger.error(f"定时任务执行失败: {e}")

            schedule.every(interval_minutes).minutes.do(scheduled_job)
            logger.info(f"已启动定时任务，每{interval_minutes}分钟执行一次，按 Ctrl+C 退出")
            # 对齐到下一个整数分钟再开始跑定时任务
            now = datetime.now()
            sleep_seconds = 60 - now.second - now.microsecond / 1_000_000
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
            while not downloader.shutdown_requested:
                schedule.run_pending()
                time.sleep(1)

        elif args.hours:
            # 持续下载模式
            print(f"启动持续下载模式，时长 {args.hours} 小时: {target_symbols}")
            downloader.download_continuous(target_symbols, args.hours)

        elif len(target_symbols) == 1:
            # 下载单个交易对
            success = downloader.download_single_symbol(target_symbols[0])
            if success:
                print(f"下载成功: {target_symbols[0]}")
            else:
                print(f"下载失败: {target_symbols[0]}")

        else:
            # 下载多个交易对
            results = downloader.download_multiple_symbols(target_symbols)
            success_count = sum(1 for success in results.values() if success)
            print(f"批量下载完成: {success_count}/{len(target_symbols)} 成功，共 {len(target_symbols)}")

    except KeyboardInterrupt:
        print("\n用户中断操作")
    except Exception as e:
        logger.error(f"程序执行出错: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
