#!/usr/bin/env bash
# =============================================================================
# yf-rag 应用入口脚本
# 可用命令: django | celery
# 启动时自动等待基础设施就绪并执行数据库迁移
# =============================================================================
set -euo pipefail

# === 超时配置 ===
WAIT_TIMEOUT=${WAIT_TIMEOUT:-120}
WAIT_INTERVAL=3

# === 颜色输出 ===
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# === TCP 端口等待 ===
wait_for_tcp() {
    local host="$1"
    local port="$2"
    local name="$3"
    local elapsed=0

    log_info "等待 ${name} (${host}:${port})..."

    while ! (echo > /dev/tcp/"${host}"/"${port}") 2>/dev/null; do
        sleep "${WAIT_INTERVAL}"
        elapsed=$((elapsed + WAIT_INTERVAL))
        if [ "${elapsed}" -ge "${WAIT_TIMEOUT}" ]; then
            log_error "连接 ${name} (${host}:${port}) 超过 ${WAIT_TIMEOUT}s 仍未就绪"
            exit 1
        fi
    done

    log_info "${name} 已就绪 (${elapsed}s)"
}

# === 等待所有基础设施 ===
wait_for_infra() {
    log_info "开始等待基础设施就绪..."

    wait_for_tcp "${DB_HOST:-127.0.0.1}" "${DB_PORT:-3306}" "MySQL"
    wait_for_tcp "${REDIS_HOST:-127.0.0.1}" "${REDIS_PORT:-6379}" "Redis"
    wait_for_tcp "${MINIO_HOST:-127.0.0.1}" "${MINIO_PORT:-9000}" "MinIO"
    wait_for_tcp "${ES_HOST:-127.0.0.1}" "${ES_PORT:-9200}" "Elasticsearch"

    log_info "所有基础设施已就绪 ✓"
}

# === 数据库迁移 ===
run_migrations() {
    log_info "开始数据库迁移..."
    python manage.py migrate --noinput
    log_info "数据库迁移完成 ✓"
}

# === 入口分发 ===
case "${1:-}" in

    django)
        wait_for_infra
        run_migrations

        log_info "启动 Django (Gunicorn)..."
        log_info "  Workers: ${GUNICORN_WORKERS:-4}"
        log_info "  Timeout: ${GUNICORN_TIMEOUT:-120}s"
        log_info "  Preload: enabled (master 加载一次，worker fork 继承)"
        log_info "  Bind:    0.0.0.0:${DJANGO_BIND_PORT:-9380}"

        # --preload: 在 master 进程中加载 Django 应用（含字典），worker 通过 fork 继承
        # 避免每个 worker 独立执行 AppConfig.ready() 导致重复加载
        exec gunicorn __000__django.wsgi:application \
            --bind "0.0.0.0:${DJANGO_BIND_PORT:-9380}" \
            --workers "${GUNICORN_WORKERS:-4}" \
            --timeout "${GUNICORN_TIMEOUT:-120}" \
            --graceful-timeout 30 \
            --max-requests 1000 \
            --max-requests-jitter 50 \
            --preload \
            --access-logfile - \
            --error-logfile - \
            --log-level info
        ;;

    celery)
        wait_for_infra
        run_migrations

        log_info "启动 Celery Worker..."
        log_info "  Pool:        eventlet"
        log_info "  Concurrency: ${CELERY_CONCURRENCY:-8}"
        log_info "  Log Level:   ${CELERY_LOG_LEVEL:-info}"

        # exec 替换当前进程，确保信号正确传递
        exec celery -A __000__django worker \
            --pool=eventlet \
            --loglevel="${CELERY_LOG_LEVEL:-info}" \
            --concurrency="${CELERY_CONCURRENCY:-8}" \
            --without-heartbeat \
            --without-mingle \
            --without-gossip \
            --max-tasks-per-child "${CELERY_MAX_TASKS_PER_CHILD:-100}"
        ;;

    "")
        log_error "未提供命令。可用命令: django | celery"
        exit 1
        ;;

    *)
        # 允许执行自定义命令
        exec "$@"
        ;;
esac
