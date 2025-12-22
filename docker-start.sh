#!/bin/bash

# Binance OI Downloader Docker 启动脚本
# 用于快速启动和停止Docker服务

set -e

PROJECT_NAME="binance-oi-downloader"
COMPOSE_FILE="docker-compose.yml"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查依赖
check_dependencies() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装，请先安装 Docker"
        exit 1
    fi

    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose 未安装，请先安装 Docker Compose"
        exit 1
    fi
}

# 检查配置文件
check_config() {
    if [ ! -f "config/config.json" ]; then
        log_warning "配置文件 config/config.json 不存在"
        if [ -f "config/config_example.json" ]; then
            log_info "复制示例配置文件..."
            cp config/config_example.json config/config.json
            log_success "已创建配置文件，请根据需要修改 config/config.json"
        else
            log_error "未找到配置文件模板，请检查 config/ 目录"
            exit 1
        fi
    fi
}

# 创建必要的目录
create_directories() {
    mkdir -p data logs
    log_info "已创建数据目录: data/, logs/"
}

# 启动服务
start_service() {
    log_info "启动 $PROJECT_NAME 服务..."

    # 停止可能存在的旧容器
    docker-compose down --remove-orphans 2>/dev/null || true

    # 启动服务
    docker-compose up -d

    # 等待服务启动
    sleep 3

    # 检查服务状态
    if docker-compose ps | grep -q "Up"; then
        log_success "服务启动成功!"

        # 显示访问信息
        container_id=$(docker-compose ps -q)
        if [ ! -z "$container_id" ]; then
            log_info "容器ID: $container_id"
        fi

        log_info "查看日志: docker-compose logs -f"
        log_info "停止服务: docker-compose down"
    else
        log_error "服务启动失败，请检查日志"
        docker-compose logs
        exit 1
    fi
}

# 停止服务
stop_service() {
    log_info "停止 $PROJECT_NAME 服务..."
    docker-compose down
    log_success "服务已停止"
}

# 重启服务
restart_service() {
    log_info "重启 $PROJECT_NAME 服务..."
    docker-compose restart
    log_success "服务已重启"
}

# 查看状态
show_status() {
    echo "=== $PROJECT_NAME 状态 ==="
    docker-compose ps

    echo -e "\n=== 容器资源使用 ==="
    container_id=$(docker-compose ps -q 2>/dev/null)
    if [ ! -z "$container_id" ]; then
        docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}" "$container_id" 2>/dev/null || true
    fi

    echo -e "\n=== 数据目录状态 ==="
    if [ -d "data" ]; then
        echo "数据目录: $(du -sh data 2>/dev/null | cut -f1)"
        if [ -f "data/binance_data.db" ]; then
            echo "数据库文件: $(ls -lh data/binance_data.db | awk '{print $5}')"
        fi
    else
        echo "数据目录不存在"
    fi
}

# 查看日志
show_logs() {
    if [ "$1" = "follow" ]; then
        docker-compose logs -f
    else
        docker-compose logs
    fi
}

# 清理资源
cleanup() {
    log_warning "这将删除所有容器、镜像和卷，确定要继续吗? (y/N)"
    read -r response
    if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        log_info "清理所有Docker资源..."
        docker-compose down -v --rmi all
        docker system prune -f
        log_success "清理完成"
    else
        log_info "已取消清理操作"
    fi
}

# 显示帮助
show_help() {
    cat << EOF
Binance OI Downloader Docker 管理脚本

用法: $0 [命令]

命令:
    start       启动服务
    stop        停止服务
    restart     重启服务
    status      查看服务状态
    logs        查看日志
    logs-f      实时查看日志
    cleanup     清理所有Docker资源（危险操作）
    help        显示此帮助信息

示例:
    $0 start     # 启动服务
    $0 logs-f    # 实时查看日志
    $0 stop      # 停止服务

EOF
}

# 主函数
main() {
    check_dependencies

    case "${1:-help}" in
        "start")
            check_config
            create_directories
            start_service
            ;;
        "stop")
            stop_service
            ;;
        "restart")
            restart_service
            ;;
        "status")
            show_status
            ;;
        "logs")
            show_logs
            ;;
        "logs-f")
            show_logs follow
            ;;
        "cleanup")
            cleanup
            ;;
        "help"|*)
            show_help
            ;;
    esac
}

# 执行主函数
main "$@"
