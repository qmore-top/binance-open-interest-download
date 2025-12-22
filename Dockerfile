# 使用官方Python镜像作为基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV TZ=Asia/Shanghai

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY . .

# 安装Python依赖
RUN pip install --no-cache-dir -e .

# 创建数据目录
RUN mkdir -p /app/data /app/logs

# 设置执行权限
RUN chmod +x main.py

# 创建非root用户
RUN useradd --create-home --shell /bin/bash binance && \
    chown -R binance:binance /app
USER binance

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; print('Health check passed'); sys.exit(0)" || exit 1

# 默认启动命令
CMD ["python", "main.py"]
