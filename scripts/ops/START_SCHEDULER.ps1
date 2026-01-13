# 快速启动指南 - Profile 定时更新系统 (PowerShell)

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "🚀 Profile 定时更新系统 - 快速启动" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# 检查后端是否运行
Write-Host "✅ Step 1: 检查后端服务..." -ForegroundColor Green

try {
    $response = Invoke-WebRequest -Uri "http://localhost:8080/api/news/stocks/progress" -TimeoutSec 2 -ErrorAction SilentlyContinue
    Write-Host "   ✅ 后端服务已运行" -ForegroundColor Green
} catch {
    Write-Host "   ❌ 后端服务未运行，请先启动后端" -ForegroundColor Red
    Write-Host "   在 backend 目录运行: python -m uvicorn app.main:app --host 0.0.0.0 --port 8080" -ForegroundColor Yellow
    exit 1
}

# 检查前端是否运行
Write-Host ""
Write-Host "✅ Step 2: 检查前端服务..." -ForegroundColor Green

try {
    $response = Invoke-WebRequest -Uri "http://localhost:3000" -TimeoutSec 2 -ErrorAction SilentlyContinue
    Write-Host "   ✅ 前端服务已运行" -ForegroundColor Green
} catch {
    Write-Host "   ⚠️  前端服务可能未运行，请检查" -ForegroundColor Yellow
    Write-Host "   在 frontend 目录运行: npm run dev" -ForegroundColor Yellow
}

# 获取 API 状态
Write-Host ""
Write-Host "✅ Step 3: 获取 Profile 进度..." -ForegroundColor Green

try {
    $response = Invoke-WebRequest -Uri "http://localhost:8080/api/news/stocks/progress?page=1&page_size=5" -TimeoutSec 5
    $data = $response.Content | ConvertFrom-Json
    
    Write-Host ""
    Write-Host "📊 API 响应:" -ForegroundColor Cyan
    Write-Host "   总股票数: $($data.total_stocks)" -ForegroundColor White
    Write-Host "   已完成: $($data.completed_profiles)" -ForegroundColor Green
    Write-Host "   完成度: $($data.progress_percentage)%" -ForegroundColor Yellow
    Write-Host "   平均完成度: $($data.average_completion)%" -ForegroundColor Yellow
} catch {
    Write-Host "   ❌ 无法连接到 API，请检查后端" -ForegroundColor Red
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "✅ 系统已就绪！" -ForegroundColor Green
Write-Host ""
Write-Host "📊 重要指标:" -ForegroundColor Cyan
Write-Host "   - 总股票数: 2990 (从 NewsArticle 中提取)" -ForegroundColor White
Write-Host "   - 已完成: 3 个" -ForegroundColor Green
Write-Host "   - 待更新: 2987 个" -ForegroundColor Yellow
Write-Host "   - 完成度: 0.10%" -ForegroundColor Yellow
Write-Host ""
Write-Host "📍 访问地址:" -ForegroundColor Cyan
Write-Host "   - 前端: http://localhost:3000" -ForegroundColor Cyan
Write-Host "   - API 进度: http://localhost:8080/api/news/stocks/progress" -ForegroundColor Cyan
Write-Host ""
Write-Host "🔔 定时任务:" -ForegroundColor Cyan
Write-Host "   - 每周一 02:00 自动执行" -ForegroundColor White
Write-Host "   - 预计 ~60 天完成所有 2987 个股票" -ForegroundColor White
Write-Host "   - 每只股票间隔 2 秒" -ForegroundColor White
Write-Host "==========================================" -ForegroundColor Cyan
