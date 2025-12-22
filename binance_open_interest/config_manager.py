"""
配置文件管理模块
负责读取和管理应用程序配置
"""

import json
import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

class ConfigManager:
    """配置管理器"""

    def __init__(self, config_file: str = "config/config.json", env_file: str = ".env"):
        """
        初始化配置管理器

        Args:
            config_file: 交易对配置文件路径 (JSON格式)
            env_file: 环境变量配置文件路径
        """
        # 加载环境变量
        load_dotenv(env_file)

        self.config_file = Path(config_file)
        self.symbols = self._load_symbols()

    def _load_symbols(self) -> List[str]:
        """
        加载交易对列表

        Returns:
            交易对列表
        """
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # 支持数组格式或对象格式
                if isinstance(data, list):
                    symbols = data
                elif isinstance(data, dict) and "symbols" in data:
                    symbols = data["symbols"]
                else:
                    symbols = []

                logger.info(f"已加载 {len(symbols)} 个交易对")
                return symbols

            except json.JSONDecodeError as e:
                logger.warning(f"配置文件解析失败: {e}")
                return []
            except Exception as e:
                logger.warning(f"读取配置文件失败: {e}")
                return []
        else:
            logger.warning(f"配置文件不存在: {self.config_file}")
            return []

    def _deep_merge(self, base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
        """
        深度合并字典

        Args:
            base: 基础字典
            update: 更新字典

        Returns:
            合并后的字典
        """
        result = base.copy()

        for key, value in update.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value

        return result

    def _save_default_config(self):
        """保存默认配置文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
            logger.info(f"已创建默认配置文件: {self.config_file}")
        except Exception as e:
            logger.warning(f"创建默认配置文件失败: {e}")

    def get_symbols(self) -> List[str]:
        """获取交易对列表"""
        return self.symbols

    def get_data_dir(self) -> str:
        """获取数据存储目录"""
        return os.getenv('DATA_DIR', 'data')

    def get_proxy_config(self) -> Dict[str, Optional[str]]:
        """获取代理配置（从环境变量）"""
        return {
            "http_proxy": os.getenv('HTTP_PROXY'),
            "https_proxy": os.getenv('HTTPS_PROXY'),
            "socks_proxy": os.getenv('SOCKS_PROXY')
        }

    def get_logging_config(self) -> Dict[str, Any]:
        """获取日志配置（从环境变量）"""
        return {
            "level": os.getenv('LOG_LEVEL', 'INFO'),
            "file_enabled": os.getenv('LOG_FILE_ENABLED', 'true').lower() == 'true'
        }

    def get_config_path(self) -> str:
        """获取配置文件路径"""
        return str(self.config_file)


    def get_proxy_config(self) -> Dict[str, Optional[str]]:
        """获取代理配置（从环境变量）"""
        return {
            "http_proxy": os.getenv('HTTP_PROXY'),
            "https_proxy": os.getenv('HTTPS_PROXY'),
            "socks_proxy": os.getenv('SOCKS_PROXY')
        }


    def get_config_summary(self) -> str:
        """获取配置摘要"""
        summary = []
        summary.append("配置摘要:")
        summary.append(f"  交易对数量: {len(self.get_symbols())}")
        summary.append(f"  数据目录: {self.get_data_dir()}")

        proxy_config = self.get_proxy_config()
        proxy_enabled = any(proxy_config.values())
        summary.append(f"  代理设置: {'启用' if proxy_enabled else '禁用'}")

        logging_config = self.get_logging_config()
        summary.append(f"  日志级别: {logging_config.get('level', 'INFO')}")
        summary.append(f"  日志文件: {'启用' if logging_config.get('file_enabled', True) else '禁用'}")

        return "\n".join(summary)

    def validate_config(self) -> List[str]:
        """
        验证配置有效性

        Returns:
            错误信息列表
        """
        errors = []

        # 验证交易对
        symbols = self.get_symbols()
        if not symbols:
            errors.append("交易对列表不能为空")

        return errors
