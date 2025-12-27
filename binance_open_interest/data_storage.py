"""
数据存储模块
负责将下载的数据存储到文件系统
"""

import os
import json
import csv
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class DataStorage:
    """数据存储管理器"""

    def __init__(self, base_dir: str = "data"):
        """
        初始化存储管理器

        Args:
            base_dir: 基础数据目录
        """
        self.base_dir = Path(base_dir)
        self.oi_dir = self.base_dir / "open_interest"
        self.errors_dir = self.base_dir / "errors"
        self.logs_dir = self.base_dir / "logs"

        # 创建目录结构
        self._create_directories()

    def _create_directories(self):
        """创建必要的目录结构"""
        directories = [
            self.base_dir,
            self.oi_dir,
            self.errors_dir,
            self.logs_dir
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            logger.debug(f"创建目录: {directory}")

        # 清理可能的中断临时文件
        self._cleanup_temp_files()

    def _cleanup_temp_files(self):
        """清理中断过程中留下的临时文件"""
        try:
            temp_files = []
            # 查找所有.tmp文件
            for pattern in ["**/*.tmp"]:
                temp_files.extend(self.base_dir.glob(pattern))

            if temp_files:
                logger.info(f"发现 {len(temp_files)} 个临时文件，正在清理...")
                for temp_file in temp_files:
                    try:
                        temp_file.unlink()
                        logger.debug(f"删除临时文件: {temp_file}")
                    except Exception as e:
                        logger.warning(f"删除临时文件失败: {temp_file} - {e}")
            else:
                logger.debug("没有发现临时文件")
        except Exception as e:
            logger.warning(f"清理临时文件时出错: {e}")

    def save_open_interest_data(self, symbol: str, data: Dict, data_type: str = "realtime") -> bool:
        """
        保存未平仓合约数据（使用UTC时间）

        Args:
            symbol: 交易对符号
            data: 未平仓合约数据
            data_type: 数据类型 ("realtime")

        Returns:
            保存是否成功
        """
        try:
            now_utc = datetime.utcnow()
            # 实时数据：按日存储 data/open_interest/{symbol}/1m/{symbol}-oi-{yyyy-mm-dd}.csv
            date_str = now_utc.strftime("%Y-%m-%d")
            filename = f"{symbol}-oi-{date_str}.csv"
            filepath = self.oi_dir / symbol / "1m" / filename

            # 确保目录存在
            filepath.parent.mkdir(parents=True, exist_ok=True)

            # 检查文件大小，如果超过10MB则进行轮转
            if filepath.exists() and filepath.stat().st_size > 10 * 1024 * 1024:  # 10MB
                self._rotate_log_file(filepath, symbol, date_str)

            # 检查文件是否存在，决定是创建新文件还是追加数据
            file_exists = filepath.exists()

            with open(filepath, 'a', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)

                # 如果是新文件，写入表头（去掉 symbol 列）
                if not file_exists:
                    writer.writerow(["timestamp", "datetime_utc", "openInterest", "sumOpenInterestValue"])

                # 写入数据（使用UTC时间）
                dt_utc = datetime.utcfromtimestamp(data.get("timestamp", 0) / 1000)
                writer.writerow([
                    data.get("timestamp", ""),
                    dt_utc.isoformat() + "Z",  # UTC时间格式
                    data.get("openInterest", ""),
                    data.get("sumOpenInterestValue", "")
                ])

            logger.info(f"保存未平仓合约数据: {filepath}")
            return True

        except Exception as e:
            logger.error(f"保存未平仓合约数据失败: {e}")
            return False

    def _rotate_log_file(self, filepath: Path, symbol: str, suffix: str):
        """
        轮转日志文件
        
        Args:
            filepath: 当前日志文件路径
            symbol: 交易对符号
            year_month: 年月标识
        """
        try:
            # 生成新的文件名，添加时间戳
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            rotated_filename = f"{symbol}-oi-{suffix}.{timestamp}.csv"
            rotated_filepath = filepath.parent / rotated_filename
            
            # 重命名文件
            filepath.rename(rotated_filepath)
            logger.info(f"日志文件已轮转: {filepath.name} -> {rotated_filename}")
        except Exception as e:
            logger.error(f"日志文件轮转失败: {e}")

    def save_error_log(self, symbol: str, error_info: Dict) -> bool:
        """
        保存错误日志

        Args:
            symbol: 交易对符号
            error_info: 错误信息字典

        Returns:
            保存是否成功
        """
        try:
            now = datetime.now()
            date_str = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H-%M-%S")

            # 创建文件名
            filename = f"error_{symbol}_{date_str}_{time_str}.json"
            # 恢复使用按日期分目录的方式保存错误日志
            filepath = self.errors_dir / date_str / filename

            # 确保日期目录存在
            filepath.parent.mkdir(parents=True, exist_ok=True)

            # 保存错误信息
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(error_info, f, indent=2, ensure_ascii=False)

            logger.info(f"保存错误日志: {filepath}")
            return True

        except Exception as e:
            logger.error(f"保存错误日志失败: {e}")
            return False

    def save_oi_history_batch(self, symbol: str, records: List[Dict]) -> bool:
        """
        保存5分钟历史数据到 data/open_interest/{symbol}/5m 目录（按天存储）

        Args:
            symbol: 交易对
            records: 历史记录列表（包含timestamp等字段）
        """
        try:
            if not records:
                return True

            # 按日期分组记录
            records_by_date = {}
            for record in records:
                ts = record.get("timestamp")
                if ts is None:
                    continue
                # 使用UTC时间
                dt = datetime.utcfromtimestamp(int(ts) / 1000)
                date_str = dt.strftime("%Y-%m-%d")

                if date_str not in records_by_date:
                    records_by_date[date_str] = []
                records_by_date[date_str].append(record)

            # 为每个日期保存数据（使用临时文件确保原子性）
            for date_str, date_records in records_by_date.items():
                filename = f"{symbol}-oi-5m-{date_str}.csv"
                filepath = self.oi_dir / symbol / "5m" / filename
                filepath.parent.mkdir(parents=True, exist_ok=True)

                # 使用临时文件确保原子性
                temp_filepath = filepath.with_suffix(".tmp")
                final_filepath = filepath

                try:
                    # 写入临时文件（历史数据每次都是完整的一天，直接覆盖）
                    with open(temp_filepath, "w", encoding="utf-8", newline="") as f:
                        writer = csv.writer(f)
                        # 历史数据表头
                        writer.writerow(["timestamp", "datetime_utc", "openInterest", "sumOpenInterestValue"])

                        for record in date_records:
                            dt = datetime.utcfromtimestamp(int(record.get("timestamp", 0)) / 1000)
                            writer.writerow([
                                record.get("timestamp", ""),
                                dt.isoformat() + "Z",  # UTC时间格式
                                record.get("sumOpenInterest", record.get("openInterest", "")),
                                record.get("sumOpenInterestValue", "")
                            ])

                    # 原子性重命名：临时文件 -> 正式文件
                    temp_filepath.replace(filepath)
                    logger.debug(f"历史数据文件写入完成: {filepath}")

                except Exception as e:
                    # 如果出错，清理临时文件
                    try:
                        if temp_filepath.exists():
                            temp_filepath.unlink()
                    except Exception:
                        pass
                    raise e

            logger.info(f"保存历史OI数据: {symbol}, {len(records)} 条记录，{len(records_by_date)} 个日期")
            return True
        except Exception as e:
            logger.error(f"保存历史OI数据失败: {e}")
            return False

    def is_date_data_exists(self, symbol: str, date_str: str) -> bool:
        """
        检查指定日期的数据文件是否存在

        Args:
            symbol: 交易对
            date_str: 日期字符串 (YYYY-MM-DD)

        Returns:
            数据文件是否存在
        """
        try:
            data_file = self.oi_dir / symbol / "5m" / f"{symbol}-oi-5m-{date_str}.csv"
            return data_file.exists() and data_file.stat().st_size > 0
        except Exception:
            return False

    def get_last_downloaded_date(self, symbol: str) -> Optional[str]:
        """
        获取指定交易对最后下载的日期

        Args:
            symbol: 交易对

        Returns:
            最后下载日期 (YYYY-MM-DD) 或 None
        """
        try:
            symbol_dir = self.oi_dir / symbol / "5m"
            if not symbol_dir.exists():
                return None

            # 查找.complete文件，找到最新的日期
            complete_files = list(symbol_dir.glob("*.complete"))
            if not complete_files:
                return None

            # 从文件名中提取日期并找到最新的
            dates = []
            for complete_file in complete_files:
                try:
                    filename = complete_file.name
                    if "-oi-5m-" in filename and filename.endswith(".complete"):
                        date_part = filename.split("-oi-5m-")[1].replace(".complete", "")
                        dates.append(date_part)
                except Exception:
                    continue

            return max(dates) if dates else None
        except Exception as e:
            logger.error(f"获取最后下载日期失败 {symbol}: {e}")
            return None

    def get_last_5m_timestamp(self, symbol: str) -> Optional[int]:
        """
        获取指定交易对5m目录的最后时间戳（毫秒）

        Args:
            symbol: 交易对

        Returns:
            最后时间戳或None
        """
        try:
            history_dir = self.oi_dir / symbol / "5m"
            if not history_dir.exists():
                return None

            files = sorted(history_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
            for file_path in files:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    for line in reversed(lines):
                        parts = line.strip().split(",")
                        if parts and parts[0].isdigit():
                            return int(parts[0])
            return None
        except Exception as e:
            logger.error(f"读取5m最后时间戳失败 {symbol}: {e}")
            return None

    def save_batch_results(self, results: Dict[str, bool], batch_info: Dict) -> bool:
        """
        保存批量下载结果摘要（追加到每日CSV，避免生成大量文件）
        
        Args:
            results: 批量下载结果
            batch_info: 批次信息
        
        Returns:
            保存是否成功
        """
        try:
            now = datetime.now()
            date_str = now.strftime("%Y-%m-%d")

            total_symbols = len(results)
            success_count = sum(1 for ok in results.values() if ok)
            failed_symbols = [s for s, ok in results.items() if not ok]

            filepath = self.logs_dir / f"batch_summary-{date_str}.csv"
            filepath.parent.mkdir(parents=True, exist_ok=True)
            file_exists = filepath.exists()

            with open(filepath, "a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow([
                        "timestamp",
                        "duration_seconds",
                        "processed_count",
                        "total_symbols",
                        "success_count",
                        "failed_symbols",
                        "interrupted"
                    ])
                writer.writerow([
                    now.isoformat(),
                    batch_info.get("duration", ""),
                    batch_info.get("processed_count", ""),
                    total_symbols,
                    success_count,
                    ";".join(failed_symbols),
                    batch_info.get("interrupted", False)
                ])

            logger.info(f"保存批量结果汇总: {filepath}")
            return True
        
        except Exception as e:
            logger.error(f"保存批量结果摘要失败: {e}")
            return False

    def get_recent_data_files(self, symbol: str, limit: int = 10) -> List[Path]:
        """
        获取指定交易对的最近数据文件

        Args:
            symbol: 交易对符号
            limit: 返回的文件数量限制

        Returns:
            数据文件路径列表
        """
        try:
            data_files = []
            
            # 查找实时数据文件 (CSV格式)
            realtime_dir = self.oi_dir / symbol / "1m"
            if realtime_dir.exists():
                for file_path in realtime_dir.glob("*.csv"):
                    data_files.append(file_path)
            
            # 按修改时间排序，返回最新的文件
            data_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            return data_files[:limit]

        except Exception as e:
            logger.error(f"获取最近数据文件失败: {e}")
            return []

    def cleanup_old_files(self, days_to_keep: int = 30):
        """
        清理旧文件

        Args:
            days_to_keep: 保留天数
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)
            deleted_count = 0

            # 清理数据文件
            for root_dir in [self.oi_dir, self.errors_dir, self.logs_dir]:
                if root_dir.exists():
                    for file_path in root_dir.rglob("*"):
                        # 只处理文件，不处理目录
                        if file_path.is_file() and file_path.stat().st_mtime < cutoff_date.timestamp():
                            # 检查是否为轮转的日志文件，如果是则可以安全删除
                            if "oi-" in file_path.name and "." in file_path.name:
                                file_parts = file_path.name.split(".")
                                if len(file_parts) >= 3 and len(file_parts[-2]) == 15:  # 符合轮转文件命名规则 (YYYYMMDD_HHMMSS)
                                    file_path.unlink()
                                    deleted_count += 1
                                    continue
                            
                            # 对于其他文件，正常删除
                            file_path.unlink()
                            deleted_count += 1

            if deleted_count > 0:
                logger.info(f"清理了 {deleted_count} 个旧文件")

        except Exception as e:
            logger.error(f"清理旧文件失败: {e}")

    def get_storage_stats(self) -> Dict:
        """
        获取存储统计信息

        Returns:
            存储统计字典
        """
        try:
            stats = {
                "total_files": 0,
                "total_size_mb": 0,
                "directories": {},
                "last_cleanup": None
            }

            for root_dir in [self.oi_dir, self.errors_dir, self.logs_dir]:
                if root_dir.exists():
                    dir_stats = {
                        "file_count": 0,
                        "size_mb": 0.0  # 明确指定为浮点数
                    }

                    for file_path in root_dir.rglob("*"):
                        if file_path.is_file():
                            dir_stats["file_count"] += 1
                            dir_stats["size_mb"] += file_path.stat().st_size / (1024 * 1024)  # type: ignore

                    stats["directories"][root_dir.name] = dir_stats
                    stats["total_files"] += dir_stats["file_count"]
                    stats["total_size_mb"] += dir_stats["size_mb"]

            return stats

        except Exception as e:
            logger.error(f"获取存储统计失败: {e}")
            return {}
