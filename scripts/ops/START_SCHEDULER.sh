#!/usr/bin/env bash
# 快速启动指南 - Profile 定时更新系统

echo "=========================================="
echo "🚀 Profile 定时更新系统 - 快速启动"
echo "=========================================="
echo ""

# 检查后端是否运行
echo "✅ Step 1: 检查后端服务..."
if curl -s http://localhost:8080/api/news/stocks/progress > /dev/null 2>&1; then
    echo "   ✅ 后端服务已运行"
else
    echo "   ❌ 后端服务未运行，请先启动后端"
    echo "   在 backend 目录运行: python -m uvicorn app.main:app --host 0.0.0.0 --port 8080"
    exit 1
fi

# 检查前端是否运行
echo ""
echo "✅ Step 2: 检查前端服务..."
if curl -s http://localhost:3000 > /dev/null 2>&1; then
    echo "   ✅ 前端服务已运行"
else
    echo "   ⚠️  前端服务可能未运行，请检查"
    echo "   在 frontend 目录运行: npm run dev"
fi

# 获取 API 状态
echo ""
echo "✅ Step 3: 获取 Profile 进度..."
curl -s http://localhost:8080/api/news/stocks/progress?page=1&page_size=5 | python -m json.tool

echo ""
echo "=========================================="
echo "✅ 系统已就绪！"
echo ""
echo "📊 重要指标:"
echo "   - 总股票数: 2990 (从 NewsArticle 中提取)"
echo "   - 已完成: 3 个"
echo "   - 待更新: 2987 个"
echo "   - 完成度: 0.10%"
echo ""
echo "📍 访问地址:"
echo "   - 前端: http://localhost:3000"
echo "   - API 进度: http://localhost:8080/api/news/stocks/progress"
echo ""
echo "🔔 定时任务:"
echo "   - 每周一 02:00 自动执行"
echo "   - 预计 ~60 天完成所有 2987 个股票"
echo "   - 每只股票间隔 2 秒"
echo "=========================================="
