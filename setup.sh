#!/bin/bash
set -e

echo "========================================"
echo "  钉钉聊天记录导出工具 - 安装脚本"
echo "========================================"
echo ""

# Check Python
echo "[1/2] 检查 Python 环境..."
if ! command -v python3 &> /dev/null; then
    if ! command -v python &> /dev/null; then
        echo "[错误] 未找到 Python，请先安装 Python 3.10+"
        exit 1
    fi
    PYTHON=python
else
    PYTHON=python3
fi

echo "  已找到 $($PYTHON --version)"

# Install dependencies
echo ""
echo "[2/2] 安装 Python 依赖..."
$PYTHON -m pip install -r requirements.txt
echo "  依赖安装完成"

echo ""
echo "========================================"
echo "  安装完成！"
echo "========================================"
echo ""
echo "运行以下命令启动工具:"
echo "  $PYTHON main.py"
echo ""
echo "然后浏览器访问 http://localhost:8090"
echo ""
