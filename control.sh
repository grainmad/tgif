#!/bin/bash

# 脚本名称
SCRIPT_NAME=$(basename "$0")
# 程序名称
PROGRAM="tgif.py"
# 虚拟环境路径
VENV_PATH="./.venv/bin/activate"
# python版本
PYTHON_VERSION="3.12.4"


# 帮助信息
usage() {
    echo "使用方法: $SCRIPT_NAME [start|stop|status|restart]"
    echo "  start         启动程序"
    echo "  stop          停止程序"
    echo "  status        查看程序状态"
    echo "  restart       重启程序"
}

# 获取程序PID
get_pid() {
    pgrep -f "$PROGRAM"
}

# 检查 Python 版本是否已安装
check_and_install_python() {
    local version=$1
    
    # 检查版本是否已安装
    if pyenv versions --bare | grep -q "^${version}$"; then
        echo "✓ Python ${version} 已安装"
        return 0
    else
        echo "✗ Python ${version} 未安装"
        
        # 提示用户
        read -p "是否要安装 Python ${version}？[y/N] " answer
        case ${answer:0:1} in
            y|Y)
                echo "正在安装 Python ${version}..."
                pyenv install ${version}
                
                # 检查安装是否成功
                if [ $? -eq 0 ]; then
                    echo "✓ Python ${version} 安装成功"
                    return 0
                else
                    echo "✗ Python ${version} 安装失败"
                    return 1
                fi
                ;;
            *)
                echo "已取消安装 Python ${version}"
                return 1
                ;;
        esac
    fi
}

# 启动程序
start() {
    # 检查是否已在运行
    if get_pid > /dev/null; then
        echo "$PROGRAM 已经在运行 (PID: $(get_pid))"
        return 1
    fi
    # 检查pyenv环境是否存在
    check_and_install_python "$PYTHON_VERSION"
    if [ $? -ne 0 ]; then
        echo "Python 环境检查或安装失败，请检查 pyenv 配置"
        return 1
    fi
    # 激活虚拟环境并启动程序
    if [ ! -f "$VENV_PATH" ]; then
        echo "创建虚拟环境 .venv"
        python -m venv .venv
    else
        echo "虚拟环境 .venv 已存在"
    fi
    source "$VENV_PATH"

    echo "检查安装依赖..."
    pip install -r requirements.txt --upgrade --upgrade-strategy only-if-needed
    
    echo "正在启动 $PROGRAM..."
    nohup python "$PROGRAM" &
    
    sleep 1  # 等待程序启动
    
    if get_pid > /dev/null; then
        echo "$PROGRAM 启动成功 (PID: $(get_pid))"
    else
        echo "$PROGRAM 启动失败"
        return 1
    fi
}

# 停止程序
stop() {
    local pid=$(get_pid)
    
    if [ -z "$pid" ]; then
        echo "$PROGRAM 没有在运行"
        return 1
    fi
    
    echo "正在停止 $PROGRAM (PID: $pid)..."
    kill "$pid"
    
    # 等待程序停止
    local count=0
    while [ $count -lt 5 ] && get_pid > /dev/null; do
        sleep 1
        ((count++))
    done
    
    if get_pid > /dev/null; then
        echo "无法停止 $PROGRAM，尝试强制停止..."
        kill -9 "$pid"
        sleep 1
    fi
    
    if ! get_pid > /dev/null; then
        echo "$PROGRAM 已停止"
    else
        echo "无法停止 $PROGRAM"
        return 1
    fi
}

# 查看程序状态
status() {
    local pid=$(get_pid)
    
    if [ -z "$pid" ]; then
        echo "$PROGRAM 没有在运行"
        return 1
    else
        echo "$PROGRAM 正在运行 (PID: $pid)"
        return 0
    fi
}

# 重启程序
restart() {
    stop
    start
}

# 主逻辑
case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    status)
        status
        ;;
    restart)
        restart
        ;;
    ""|help|--help|-h)
        usage
        ;;
    *)
        echo "未知选项: $1"
        usage
        exit 1
        ;;
esac

exit 0
