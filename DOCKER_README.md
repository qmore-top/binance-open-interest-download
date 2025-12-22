# Binance OI Downloader - Docker 部署指南

## 🚀 快速开始

### 1. 环境准备

确保系统已安装 Docker 和 Docker Compose：

```bash
# 检查安装
docker --version
docker-compose --version
```

### 2. 配置文件准备

```bash
# 进入项目目录
cd binance-open-interest-downloader

# 确保配置文件存在
ls config/config.json

# 如果不存在，复制示例配置
cp config/config_example.json config/config.json
```

### 3. 启动服务

```bash
# 构建并启动服务
docker-compose up -d

# 查看启动日志
docker-compose logs -f
```

### 4. 验证运行

```bash
# 检查容器状态
docker-compose ps

# 查看运行日志
docker-compose logs binance-oi-downloader
```

## 📁 目录结构

```
binance-open-interest-downloader/
├── config/                 # 配置文件目录
│   └── config.json        # 主配置文件
├── data/                  # 数据存储目录（自动创建）
│   ├── binance_data.db   # SQLite数据库
│   ├── logs/             # 应用日志
│   └── open_interest/    # 下载的数据文件
├── docker-compose.yml    # Docker Compose 配置
├── Dockerfile           # Docker 镜像构建文件
└── .dockerignore       # Docker 忽略文件
```

## ⚙️ 配置选项

### 环境变量

创建 `.env` 文件来自定义配置：

```bash
cp env.example .env
```

编辑 `.env` 文件：

```bash
# 代理设置（可选）
HTTP_PROXY=http://127.0.0.1:7897
HTTPS_PROXY=http://127.0.0.1:7897
SOCKS_PROXY=socks5://127.0.0.1:7897

# 时区设置
TZ=Asia/Shanghai

# 项目名称
COMPOSE_PROJECT_NAME=binance-oi-downloader
```

### 自定义数据目录

修改 `docker-compose.yml` 中的挂载路径：

```yaml
volumes:
  - ./config:/app/config:ro          # 配置目录（只读）
  - /custom/data/path:/app/data     # 自定义数据目录
  - /custom/logs/path:/app/logs     # 自定义日志目录
```

## 🛠️ 常用命令

### 服务管理

```bash
# 启动服务
docker-compose up -d

# 停止服务
docker-compose down

# 重启服务
docker-compose restart

# 查看日志
docker-compose logs -f

# 查看容器状态
docker-compose ps
```

### 容器操作

```bash
# 进入容器
docker-compose exec binance-oi-downloader bash

# 查看容器资源使用
docker stats

# 查看容器日志
docker-compose logs binance-oi-downloader
```

### 调试和维护

```bash
# 重新构建镜像
docker-compose build --no-cache

# 清理未使用的镜像
docker image prune -f

# 清理停止的容器
docker container prune -f

# 完全清理
docker-compose down -v --rmi all
```

## 🔧 高级配置

### 自定义启动命令

在 `docker-compose.yml` 中修改 command：

```yaml
command: ["python", "main.py", "--data-dir", "/app/custom-data"]
```

### 资源限制

调整容器资源使用：

```yaml
deploy:
  resources:
    limits:
      memory: 1G      # 内存限制
      cpus: '1.0'     # CPU限制
    reservations:
      memory: 512M    # 内存预留
      cpus: '0.5'     # CPU预留
```

### 健康检查

查看健康状态：

```bash
docker ps
# 查看 STATUS 列中的健康状态
```

### 日志轮转

日志自动轮转配置在 `docker-compose.yml` 中：

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"   # 单个日志文件最大10MB
    max-file: "3"     # 保留3个日志文件
```

## 🐛 故障排除

### 常见问题

#### 1. 配置文件未找到

**错误**: `config.json not found`

**解决**:
```bash
# 确保配置文件存在
ls -la config/config.json

# 检查文件权限
chmod 644 config/config.json
```

#### 2. 数据目录权限问题

**错误**: `Permission denied`

**解决**:
```bash
# 修复目录权限
sudo chown -R $USER:$USER data/
sudo chown -R $USER:$USER logs/
```

#### 3. 代理连接失败

**错误**: `Connection timeout`

**解决**:
```bash
# 检查代理设置
docker-compose exec binance-oi-downloader env | grep -i proxy

# 更新代理配置
vim .env
docker-compose restart
```

#### 4. 磁盘空间不足

**错误**: `No space left on device`

**解决**:
```bash
# 检查磁盘使用
df -h

# 清理Docker资源
docker system prune -f

# 移动数据目录到更大磁盘
vim docker-compose.yml  # 修改挂载路径
```

### 日志分析

```bash
# 查看最近的错误日志
docker-compose logs --tail=100 binance-oi-downloader | grep ERROR

# 查看启动日志
docker-compose logs binance-oi-downloader | head -50

# 实时监控日志
docker-compose logs -f binance-oi-downloader
```

## 📊 监控和维护

### 定期维护任务

```bash
# 每周清理一次日志
docker-compose exec binance-oi-downloader find /app/logs -name "*.log" -mtime +7 -delete

# 每月备份数据
docker-compose exec binance-oi-downloader cp /app/data/binance_data.db /app/data/backup_$(date +%Y%m%d).db

# 检查数据库大小
docker-compose exec binance-oi-downloader ls -lh /app/data/binance_data.db
```

### 性能监控

```bash
# 监控容器资源使用
docker stats $(docker-compose ps -q)

# 查看应用性能
docker-compose exec binance-oi-downloader python -c "
import psutil
import os
print(f'CPU使用: {psutil.cpu_percent()}%')
print(f'内存使用: {psutil.virtual_memory().percent}%')
print(f'磁盘使用: {psutil.disk_usage(\"/app/data\").percent}%')
"
```

## 🔒 安全建议

### 生产环境部署

1. **使用外部数据库**: 将SQLite替换为PostgreSQL/MySQL
2. **配置网络隔离**: 使用内部网络，只暴露必要端口
3. **定期更新**: 保持Docker镜像和依赖最新
4. **监控告警**: 设置日志监控和告警机制

### 数据备份

```yaml
# 添加备份服务到 docker-compose.yml
services:
  backup:
    image: alpine
    command: sh -c "while true; do cp /data/binance_data.db /backup/$(date +%Y%m%d_%H%M%S).db; sleep 86400; done"
    volumes:
      - ./data:/data:ro
      - ./backup:/backup
```

## 📞 支持

如果遇到问题，请：

1. 查看日志：`docker-compose logs binance-oi-downloader`
2. 检查配置：`docker-compose exec binance-oi-downloader cat /app/config/config.json`
3. 查看容器状态：`docker-compose ps`
4. 提交Issue：提供完整的错误日志和配置信息

---

**最后更新**: 2025-12-19
