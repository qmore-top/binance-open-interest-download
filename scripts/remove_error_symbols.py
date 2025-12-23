"""
移除错误统计中标记为无效的交易对，更新 config/config.json。
"""
from pathlib import Path
import json

# 常量：错误统计文件路径，中文解释见注释
ERROR_STATS_FILE = Path("data/error_statistics.json")
CONFIG_FILE = Path("config/config.json")


def load_error_stats():
    """读取错误统计文件"""
    if not ERROR_STATS_FILE.exists():
        print("错误统计文件不存在，无法移除交易对")
        return None
    try:
        with open(ERROR_STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"读取错误统计文件失败: {exc}")
        return None


def find_invalid_symbols(error_stats):
    """从错误统计中筛选无效交易对"""
    removable = set()
    for item in error_stats.get("details", []):
        err_type = str(item.get("error_type", "")).lower()
        msg = str(item.get("error_message", "")).lower()
        symbol = item.get("symbol")
        if not symbol:
            continue
        if err_type == "api_error" and ("1121" in msg or "invalid symbol" in msg):
            removable.add(symbol)
    return removable


def load_config_symbols():
    """读取配置文件中的交易对列表"""
    if not CONFIG_FILE.exists():
        print("配置文件不存在，无法更新")
        return None, None
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config_symbols = json.load(f)
    except Exception as exc:
        print(f"读取配置文件失败: {exc}")
        return None, None

    if isinstance(config_symbols, dict) and "symbols" in config_symbols:
        return config_symbols.get("symbols", []), True
    if isinstance(config_symbols, list):
        return config_symbols, False

    print("配置文件格式不支持，仅支持数组或包含 symbols 字段的对象")
    return None, None


def save_config(symbols, as_dict):
    """按原格式写回配置文件"""
    payload = {"symbols": symbols} if as_dict else symbols
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return True
    except Exception as exc:
        print(f"保存配置文件失败: {exc}")
        return False


def main():
    # 读取错误统计
    error_stats = load_error_stats()
    if not error_stats:
        return

    removable = find_invalid_symbols(error_stats)
    if not removable:
        print("未发现需要移除的不可恢复交易对（仅筛选无效符号/客户端错误）")
        return

    print(f"发现 {len(removable)} 个需要移除的交易对: {', '.join(sorted(removable))}")

    # 读取配置
    symbols, as_dict = load_config_symbols()
    if symbols is None:
        return

    original_count = len(symbols)
    filtered_symbols = [s for s in symbols if s not in removable]
    removed_count = original_count - len(filtered_symbols)

    if removed_count == 0:
        print("配置文件中未包含需要移除的交易对")
        return

    if save_config(filtered_symbols, as_dict):
        print(f"成功移除 {removed_count} 个交易对，剩余 {len(filtered_symbols)} 个")


if __name__ == "__main__":
    main()
