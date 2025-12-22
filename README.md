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

## Project Structure

```
binance-open-interest-downloader/
├── binance_open_interest/     # Main package directory
│   ├── __init__.py           # Package initialization
│   ├── binance_downloader.py # Binance data downloader
│   ├── data_storage.py       # File storage management
│   ├── error_handler.py      # Error handling and retry logic
│   └── config_manager.py     # Configuration manager
├── config/                   # Configuration directory
│   ├── config.json           # Trading pairs configuration
│   └── proxy_config_example.txt # Proxy configuration guide
├── env                       # Environment variables configuration
├── main.py                   # Main program entry point
├── run.py                    # Simplified run script
├── pyproject.toml            # Project configuration
├── README.md                 # Project documentation
├── LICENSE                   # License
└── .gitignore               # Git ignore file
```

## 安装

### 使用 uv（推荐）

```bash
# Clone the repository
git clone https://github.com/your-repo/binance-open-interest-downloader.git
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

### Configuration Files

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
python -m binance_open_interest
```

### 配置优先级

命令行参数 > 环境变量(.env) > 配置文件

### Automatic Symbol Updates

The program provides two versions of configuration update scripts:

#### Online Version (Recommended)
Fetch real-time trading volume data from Binance:

```bash
python update_config_with_top_symbols.py
```

This script will:
- Fetch 24-hour trading volume data for all perpetual contracts from Binance API
- Sort by volume and select top 100
- Automatically update `config.json` file
- Display statistics and update results

> ⚠️ **Note**: Requires network connection, may need proxy configuration

#### Demo Version
Uses preset data, no network connection required:

```bash
python scripts/update_config_demo.py
```

This version uses preset data for top 100 contracts by volume, suitable for testing and demonstrations.

> 💡 **Tip**: Start with the demo version to familiarize yourself with the functionality, then use the online version as needed for latest data

## 使用示例

```bash
python main.py --symbols BTCUSDT           # 1 分钟实时调度（默认每分钟）
python main.py --hours 4 --symbols BTCUSDT # 持续模式，整数分钟循环
python main.py --history-only --symbols BTCUSDT # 仅跑 5m 历史补数
python main.py --cleanup 30                # 清理 30 天前数据
python main.py --stats                     # 查看存储统计
```

### 时间对齐
- 实时 1m：按整数分钟调度与存储
- 历史 5m：每 5 分钟巡检，窗口为最近 30 天（预留 1 小时缓冲）

### 代理设置
- 命令行：`--http-proxy/--https-proxy/--socks-proxy`
- 环境变量：`HTTP_PROXY` / `HTTPS_PROXY` / `SOCKS_PROXY`
详见 `proxy_config_example.txt`。

### 数据管理
```bash
python main.py --stats      # 查看存储统计
python main.py --export     # 导出数据
python main.py --cleanup 30 # 清理 30 天前数据
```

## 命令行参数（摘要）

- `--symbols/-S` 指定交易对，留空则用配置文件
- `--hours/-c` 持续模式（单位小时，按整数分钟循环）
- `--history-only` 仅跑 5m 历史补数
- `--cleanup` 清理早于指定天数的数据
- `--stats` 查看存储统计
- `--export` 导出数据
- 代理：`--http-proxy` / `--https-proxy` / `--socks-proxy`

## 数据存储与恢复

- 1m 实时：`data/open_interest/{symbol}/1m/{symbol}-oi-YYYY-MM-DD.csv`
- 5m 历史：`data/open_interest/{symbol}/5m/{symbol}-oi-5m-YYYY-MM-DD.csv`
- 批量汇总：`data/logs/batch_summary-YYYY-MM-DD.csv`（按日追加）
- 日志：`data/logs/binance_oi_downloader.log`
- 断点恢复：扫描文件补缺口，信号（Ctrl+C/SIGTERM）前保存状态

## 时间戳与频率
- 实时 1m：按整数分钟请求与写入
- 历史 5m：仅最近 30 天，巡检间隔 5 分钟，预留 1 小时缓冲

## 默认交易对

```
BTCUSDT, ETHUSDT, BNBUSDT, ADAUSDT, XRPUSDT,
SOLUSDT, DOTUSDT, DOGEUSDT, AVAXUSDT, LTCUSDT,
BCHUSDT, LINKUSDT, UNIUSDT, ALGOUSDT, VETUSDT
```

## Error Handling

- Automatic retry for failed requests
- Historical data fallback for download failures
- Comprehensive error logging
- Support for multiple error type classifications

## File-based Interruption Recovery

The program supports **file-based seamless recovery** from interruptions, ensuring **no data is lost** when the program crashes or is forcefully terminated. The system uses filesystem scanning to detect and backfill missing data.

### How File-based Recovery Works

- **State Persistence**: Running tasks are saved to `running_tasks.json` with timestamps
- **Filesystem Scanning**: On recovery, scans existing data files to identify missing timestamps
- **Gap Detection**: Calculates expected 5-minute intervals and finds missing data points
- **Data Backfill**: Downloads missing data using exact timestamps from missed intervals
- **Graceful Shutdown**: SIGINT (Ctrl+C) and SIGTERM signals save task state before exit
- **Smart Recovery**: On startup, offers options to resume with or without data backfill

### Recovery Process

When you restart the program after an interruption:

1. **Detection**: Program loads `running_tasks.json` to detect incomplete tasks
2. **Filesystem Scan**: Analyzes existing data files to determine data completeness
3. **Gap Analysis**: Identifies missing 5-minute intervals based on task start time
4. **Backfill Option**: Offers to download missing data from interruption period
5. **Resume**: Tasks continue from last execution with gap-filled data

### Task Types with File Recovery

- **Scheduled Downloads**: Scans filesystem and backfills missing 5-minute intervals
- **Continuous Downloads**: Detects time gaps and offers to fill missing periods
- **Batch Downloads**: Resumes from interruption point (filesystem ensures no duplicates)

### Data Integrity Guarantee

- **No Data Loss**: Interruption periods are detected and missing data can be backfilled
- **Idempotent Operations**: Batch downloads are safe to resume (no duplicate data)
- **Time Precision**: Backfilled data uses exact timestamps from missed execution times
- **Progress Tracking**: Real-time progress updates ensure recovery accuracy
- **Interval Adaptation**: Automatic adjustment to Binance-supported time intervals (minimum 5 minutes)
- **Historical Data Estimation**: Fallback to kline-based OI estimation when historical OI unavailable

### Time Interval Handling

The program uses **fixed 5-minute intervals** for all operations:

#### OI Data Requirements
- **Fixed Interval**: Always uses 5-minute intervals (Binance OI History API requirement)
- **API Rate Limits**: 1000 requests per 5 minutes for OI History endpoint
- **Data Retention**: Only last 30 days of data available
- **Reliability**: 5-minute interval provides consistent and reliable data

### Manual Recovery

```bash
# View and manage incomplete tasks
python main.py --resume

# Or simply run without arguments to see recovery options
python main.py
```

### Recovery Scenarios

#### Scenario 1: Server Crash During Scheduled Download
- **Before**: Data from crash period permanently lost
- **After**: System detects time gap and offers to backfill all missed executions

#### Scenario 2: Network Interruption During Continuous Download
- **Before**: Missing data points from interruption period
- **After**: System identifies gaps and can restore recent missed downloads

#### Scenario 3: Manual Termination (Ctrl+C)
- **Before**: Partial batch download lost
- **After**: Batch resumes from exact interruption point

### Example Recovery Session

```
⚠️  Detected incomplete tasks from previous interrupted sessions:
  1. scheduled task: scheduled_1703123456 (3 symbols)
     Progress: 120 executions completed, last at 2024-01-15 14:30:00
  2. continuous task: continuous_1703123567 (2 symbols)
     Progress: 45 downloads completed, last at 2024-01-15 14:45:00

Choose an option:
  1. Resume all incomplete tasks
  2. Resume specific task (enter task number)
  3. Clean up incomplete tasks (mark as completed)
  4. Continue with new task
  5. Exit

Enter your choice (1-5): 1

🔄 Missed Executions Detected:
   Last execution: 2024-01-15T14:30:00
   Time gap: 45 minutes
   Missed executions: 45
   This will download 135 data points
   Backfill missed data? (y/N): y

Starting data backfill for 45 executions...
Backfilling execution 1/45 at 2024-01-15T14:31:00...
Backfilling execution 2/45 at 2024-01-15T14:32:00...
...
Data backfill completed: 45/45 executions, 132 total data points
```

## Docker 部署

### 使用 Docker Compose

1. **准备配置文件和环境变量**
```bash
# 确保 config/config.json 存在且配置正确
cp config/config_example.json config/config.json

# 配置环境变量（MySQL密码等）
cp env.example .env
# 编辑 .env 文件，设置 MySQL 密码等配置
```

2. **启动服务**
```bash
# 使用 Docker Compose 启动（包含 MySQL）
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

# 编辑环境变量
vim .env
```

**MySQL配置**：
```bash
# 在 .env 文件中设置 MySQL 配置
MYSQL_ROOT_PASSWORD=your_mysql_password
MYSQL_DATABASE=binance_oi
MYSQL_USERNAME=root

# 或者在 docker-compose.yml 中直接设置
environment:
  - MYSQL_ROOT_PASSWORD=your_password
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

## License

MIT License

## Contributing

Issues and Pull Requests are welcome!
