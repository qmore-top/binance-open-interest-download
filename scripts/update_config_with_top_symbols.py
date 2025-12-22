#!/usr/bin/env python3
"""
更新配置文件为交易量前100名的永续合约
从币安API获取数据并自动更新config.json
"""

import requests
import json
import time
from pathlib import Path
from typing import List, Dict, Any
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BinanceSymbolUpdater:
    """币安交易对更新器"""

    BASE_URL = "https://fapi.binance.com"

    def __init__(self, proxy: Dict[str, str] = None):
        """
        初始化更新器

        Args:
            proxy: 代理配置字典
        """
        self.proxy = proxy
        self.session = requests.Session()
        if proxy:
            self.session.proxies.update(proxy)

    def _make_request(self, endpoint: str, params: Dict = None, max_retries: int = 3) -> Dict:
        """
        发送请求到币安API

        Args:
            endpoint: API端点
            params: 请求参数
            max_retries: 最大重试次数

        Returns:
            API响应数据
        """
        url = f"{self.BASE_URL}{endpoint}"

        for attempt in range(max_retries):
            try:
                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.warning(f"请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                else:
                    raise

        raise Exception(f"API请求失败: {endpoint}")

    def get_top_volume_symbols(self, limit: int = 100) -> List[str]:
        """
        获取交易量排名前N的永续合约

        Args:
            limit: 返回的交易对数量限制

        Returns:
            排序后的交易对符号列表
        """
        logger.info("正在获取币安永续合约交易量数据...")

        # 获取24小时价格变动数据（包含交易量）
        ticker_data = self._make_request("/fapi/v1/ticker/24hr")

        # 过滤并排序交易量数据
        volume_data = []
        for ticker in ticker_data:
            try:
                symbol = ticker['symbol']
                # 只选择USDT本位的永续合约
                if symbol.endswith('USDT'):
                    volume = float(ticker.get('volume', 0))
                    if volume > 0:  # 只包含有交易量的合约
                        volume_data.append({
                            'symbol': symbol,
                            'volume': volume,
                            'quoteVolume': float(ticker.get('quoteVolume', 0))
                        })
            except (KeyError, ValueError) as e:
                logger.debug(f"跳过无效数据: {ticker.get('symbol', 'unknown')} - {e}")
                continue

        # 按交易量排序（从高到低）
        volume_data.sort(key=lambda x: x['volume'], reverse=True)

        # 取前N名
        top_symbols = [item['symbol'] for item in volume_data[:limit]]

        logger.info(f"成功获取前{limit}名交易量最大的永续合约")
        logger.info(f"第一名: {top_symbols[0]} (交易量: {volume_data[0]['volume']:,.0f})")
        logger.info(f"第一百名: {top_symbols[-1]} (交易量: {volume_data[limit-1]['volume']:,.0f})")

        return top_symbols

    def update_config_file(self, symbols: List[str], config_file: str = "config.json") -> bool:
        """
        更新配置文件

        Args:
            symbols: 交易对列表
            config_file: 配置文件路径

        Returns:
            更新是否成功
        """
        try:
            config_path = Path(config_file)

            # 读取现有配置
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            else:
                config = {}

            # 更新交易对列表
            config['symbols'] = symbols

            # 添加更新时间戳
            config['_last_updated'] = {
                'timestamp': int(time.time()),
                'datetime': time.strftime('%Y-%m-%d %H:%M:%S'),
                'method': 'top_volume_update'
            }

            # 保存配置
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

            logger.info(f"配置文件已更新: {config_path}")
            logger.info(f"包含 {len(symbols)} 个交易对")

            return True

        except Exception as e:
            logger.error(f"更新配置文件失败: {e}")
            return False

    def show_statistics(self, symbols: List[str]):
        """
        显示统计信息

        Args:
            symbols: 交易对列表
        """
        print("\n📊 交易量前100名永续合约统计")
        print("=" * 50)
        print(f"总数量: {len(symbols)}")
        print(f"前10名: {', '.join(symbols[:10])}")
        print(f"第91-100名: {', '.join(symbols[90:100])}")

        # 按币种统计
        coin_counts = {}
        for symbol in symbols:
            if symbol.endswith('USDT'):
                base_coin = symbol[:-4]  # 移除USDT后缀
                coin_counts[base_coin] = coin_counts.get(base_coin, 0) + 1

        print("\n🏆 币种分布Top 10:")
        sorted_coins = sorted(coin_counts.items(), key=lambda x: x[1], reverse=True)
        for coin, count in sorted_coins[:10]:
            print(f"  {coin}: {count} 个合约")

def main():
    """主函数"""
    print("🚀 币安永续合约交易量排名更新工具")
    print("=" * 50)

    try:
        # 初始化更新器（支持代理）
        import os
        proxy = None
        if os.getenv('HTTP_PROXY') or os.getenv('SOCKS_PROXY'):
            proxy = {}
            if os.getenv('HTTP_PROXY'):
                proxy['http'] = os.getenv('HTTP_PROXY')
                proxy['https'] = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY')
            if os.getenv('SOCKS_PROXY'):
                proxy['http'] = os.getenv('SOCKS_PROXY')
                proxy['https'] = os.getenv('SOCKS_PROXY')

        updater = BinanceSymbolUpdater(proxy=proxy)

        # 获取前100名交易量最大的永续合约
        print("正在从币安获取交易量数据...")
        top_symbols = updater.get_top_volume_symbols(limit=100)

        # 显示统计信息
        updater.show_statistics(top_symbols)

        # 更新配置文件
        print("\n正在更新配置文件...")
        success = updater.update_config_file(top_symbols, "config/config.json")

        if success:
            print("✅ 配置文件更新成功！")
            print("现在可以运行 python main.py 启动定时下载了。")
        else:
            print("❌ 配置文件更新失败！")
            return 1

    except Exception as e:
        logger.error(f"更新失败: {e}")
        print(f"\n❌ 更新过程中发生错误: {e}")
        print("请检查网络连接和代理设置。")
        return 1

    return 0

if __name__ == "__main__":
    exit(main())
