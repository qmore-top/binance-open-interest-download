# Binance Open Interest Downloader

用于下载币安合约未平仓数据（Open Interest），支持文件存储、断点恢复、实时/历史多频率拉取。

## 功能特点

- 🚀 下载币安合约未平仓量（OI）数据
- 🕒 实时 1m 调度（默认每 1 分钟），历史 5m 循环补数（每 5 分钟巡检，30 天窗口）
- 🛡️ 完整的错误处理与重试，支持兜底补全
- 📁 文件存储，按日切分：`data/open_interest/{symbol}/1m/…-YYYY-MM-DD.csv`、`5m/…-YYYY-MM-DD.csv`
- 🔄 **基于文件的断点恢复**：扫描缺口并补数
- 📊 内置存储统计
- 🏗️ 环境变量 + JSON 配置，命令行参数优先

## 项目结构

```
binance-open-interest-downloader/
├── binance_open_interest/     # 主包目录
│   ├── __init__.py           # 包初始化
│   ├── binance_downloader.py # 负责拉取数据
│   ├── data_storage.py       # 文件存储管理
│   ├── error_handler.py      # 错误处理与重试逻辑
│   └── config_manager.py     # 配置管理
├── config/                   # 配置目录
│   ├── config.json           # 交易对配置
│   └── proxy_config_example.txt # 代理配置示例
├── env                       # 环境变量目录
├── main.py                   # 主入口
├── run.py                    # 简化运行脚本
├── pyproject.toml            # 项目配置
├── README.md                 # 文档
├── LICENSE                   # 许可证
└── .gitignore               # 忽略文件
```

## 安装

### 使用 uv（推荐）

```bash
# 克隆仓库
git clone git@github.com:qmore-top/binance-open-interest-download.git
cd binance-open-interest-downloader

# 安装依赖（已包含 SOCKS 代理支持）
uv sync
```

### 传统安装

```bash
pip install -e .
```

> 说明：需要 SOCKS 代理时，依赖已包含 `PySocks`。

## 配置

程序使用两份配置：`.env`（环境变量）和 `config/config.json`（交易对列表）。

### 配置文件

1. **`.env`**（注意文件名）- 环境变量  

   ```bash
   # 日志
   LOG_LEVEL=INFO
   LOG_FILE_ENABLED=true
   # 代理
   HTTP_PROXY=http://127.0.0.1:7897
   HTTPS_PROXY=http://127.0.0.1:7897
   SOCKS_PROXY=socks5://127.0.0.1:7897
   # 数据目录
   DATA_DIR=data
   ```

2. **`config/config.json`** - 交易对列表（JSON 数组）：

```json
[
  "BTCUSDT",
  "ETHUSDT",
  "BNBUSDT",
  "ADAUSDT",
  "XRPUSDT",
  "SOLUSDT",
  "DOTUSDT",
  "DOGEUSDT"
]
```

### 启动方式

```bash
python main.py               # 使用配置文件的交易对
python main.py --symbols BTCUSDT ETHUSDT   # 指定交易对
python main.py --hours 4 --symbols BTCUSDT # 持续模式，按分钟循环
```
> 说明：`python -m binance_open_interest` 等价于运行 `python main.py`，推荐直接使用后者。

### 配置优先级

命令行参数 > 环境变量(.env) > 配置文件

### 交易对自动更新

提供两种更新脚本：

#### 在线版（推荐）
从币安获取实时 24h 交易量，选择前 100 并写入配置：

```bash
python update_config_with_top_symbols.py
```

脚本会：
- 拉取所有永续合约的 24h 交易量
- 按成交量排序并选取前 100
- 自动更新 `config.json`
- 输出统计与更新结果

> ⚠️ 需要网络，可能需代理

## 使用示例

```bash
python main.py --symbols BTCUSDT                 # 1 分钟实时调度
python main.py --hours 4 --symbols BTCUSDT       # 持续模式，按整数分钟循环
python main.py --history-only --symbols BTCUSDT  # 仅跑 5m 历史补数
python main.py --cleanup 30                      # 清理 30 天前数据
python main.py --stats                           # 查看存储统计
```

### 移除无效交易对

根据错误统计移除无效符号（独立脚本）：

```bash
python scripts/remove_error_symbols.py
```

### 时间对齐
- 实时 1m：按整数分钟调度与存储
- 历史 5m：每 5 分钟巡检，窗口为最近 30 天（预留 1 小时缓冲）

### 代理设置

- 环境变量：`HTTP_PROXY` / `HTTPS_PROXY` / `SOCKS_PROXY`
详见 `proxy_config_example.txt`。

## 命令行参数（摘要）

- `--symbols/-S` 指定交易对，留空则用配置文件
- `--hours/-c` 持续模式（单位小时，按整数分钟循环）
- `--history-only` 仅跑 5m 历史补数
- `--cleanup` 清理早于指定天数的数据
- `--stats` 查看存储统计
- 代理：环境变量 `HTTP_PROXY` / `HTTPS_PROXY` / `SOCKS_PROXY`

## 数据存储与恢复

- 1m 实时：`data/open_interest/{symbol}/1m/{symbol}-oi-YYYY-MM-DD.csv`
- 5m 历史：`data/open_interest/{symbol}/5m/{symbol}-oi-5m-YYYY-MM-DD.csv`
- 批量汇总：`data/logs/batch_summary-YYYY-MM-DD.csv`（按日追加）
- 日志：`data/logs/binance_oi_downloader.log`
- 信号中断：支持 Ctrl+C/SIGTERM 优雅退出

## 时间戳与频率
- 实时 1m：按整数分钟请求与写入
- 历史 5m：仅最近 30 天，巡检间隔 5 分钟，预留 1 小时缓冲

## 默认交易对

```
BTCUSDT, ETHUSDT, BNBUSDT, ADAUSDT, XRPUSDT,
SOLUSDT, DOTUSDT, DOGEUSDT, AVAXUSDT, LTCUSDT,
BCHUSDT, LINKUSDT, UNIUSDT, ALGOUSDT, VETUSDT
```

## 错误处理

- 请求失败的错误分类与记录
- 5m 历史拉取失败的兜底记录
- 错误统计写入 `data/error_statistics.json`

## Docker 部署

### 使用 Docker Compose

1. **准备配置文件和环境变量**
```bash
# 确保 config/config.json 存在且配置正确
cp config/config_example.json config/config.json

# 配置环境变量（代理/日志等）
cp env.example .env
# 编辑 .env 文件，根据需要调整代理、日志级别等
```

2. **启动服务**
```bash
# 使用 Docker Compose 启动
docker-compose up -d

# 查看启动日志
docker-compose logs -f

# 单独查看应用日志
docker-compose logs -f binance-oi-downloader

# 停止服务
docker-compose down
```

3. **自定义配置**

**环境变量**：
```bash
# 复制环境变量模板
cp env.example .env

# 编辑环境变量（如代理、日志级别等）
vim .env
```

**挂载自定义目录**：
```yaml
# 在 docker-compose.yml 中修改挂载路径
volumes:
  - /host/path/config:/app/config:ro
  - /host/path/data:/app/data
```

### Docker 命令

```bash
# 构建镜像
docker-compose build

# 启动并查看日志
docker-compose up

# 后台运行
docker-compose up -d

# 进入容器
docker-compose exec binance-oi-downloader bash

# 重启服务
docker-compose restart

# 停止并删除容器
docker-compose down

# 清理所有资源
docker-compose down -v --rmi all
```

### 故障排除

**查看容器状态**：
```bash
docker-compose ps
```

**查看详细日志**：
```bash
docker-compose logs binance-oi-downloader
```

**检查配置文件挂载**：
```bash
docker-compose exec binance-oi-downloader ls -la /app/config/
```

**检查数据目录权限**：
```bash
docker-compose exec binance-oi-downloader ls -la /app/data/
```

## 许可证

MIT License

## 贡献

欢迎提交 Issue 与 PR
