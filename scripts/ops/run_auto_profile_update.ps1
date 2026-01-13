# AI Stock - Profile 自动更新启动脚本 (PowerShell)
# 这个脚本会自动启动后端服务并触发所有股票的 Profile 更新

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "🤖 AI Stock - Profile 自动更新启动器" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

# 设置工作目录
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

# 1. 检查依赖
Write-Host "🔍 检查依赖..." -ForegroundColor Yellow
try {
    python -c "import apscheduler" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ APScheduler 未安装，正在安装..." -ForegroundColor Red
        pip install apscheduler
    } else {
        Write-Host "✅ APScheduler 已安装" -ForegroundColor Green
    }
} catch {
    Write-Host "⚠️ 检查依赖时出错，继续..." -ForegroundColor Yellow
}

# 2. 启动后端服务
Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "🚀 正在启动后端服务..." -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

# 设置环境变量
$env:ENABLE_SCHEDULER = '1'

Write-Host "📋 命令: python -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000" -ForegroundColor Gray
Write-Host "⏳ 等待后端服务初始化... (大约 5-10 秒)" -ForegroundColor Yellow

# 启动后端服务（在新窗口中）
Start-Process powershell -ArgumentList "-NoExit -Command `"cd '$projectRoot'; python -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000`""

# 等待后端启动
Start-Sleep -Seconds 5

# 3. 检查后端是否就绪
Write-Host "🔗 检查后端连接..." -ForegroundColor Yellow
$maxRetries = 10
$connected = $false

for ($i = 1; $i -le $maxRetries; $i++) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            Write-Host "✅ 后端服务已就绪" -ForegroundColor Green
            $connected = $true
            break
        }
    } catch {
        if ($i -lt $maxRetries) {
            Write-Host "⏳ 后端未就绪，重试... ($i/$maxRetries)" -ForegroundColor Yellow
            Start-Sleep -Seconds 2
        }
    }
}

if (-not $connected) {
    Write-Host "❌ 后端无法连接，请检查日志" -ForegroundColor Red
    exit 1
}

# 4. 触发 Profile 更新
Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "🎯 正在触发 Profile 批量更新..." -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

$payload = @{
    delay_between_stocks = 3.0
} | ConvertTo-Json

try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/api/admin/run-profile-update" `
        -Method POST `
        -ContentType "application/json" `
        -Body $payload `
        -UseBasicParsing `
        -TimeoutSec 10
    
    if ($response.StatusCode -eq 200) {
        Write-Host "✅ 更新任务已启动" -ForegroundColor Green
        $result = $response.Content | ConvertFrom-Json
        Write-Host "📋 响应:" -ForegroundColor Gray
        Write-Host ($result | ConvertTo-Json -Depth 5) -ForegroundColor Gray
    } else {
        Write-Host "❌ 启动更新失败: HTTP $($response.StatusCode)" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "❌ 触发更新异常: $_" -ForegroundColor Red
    exit 1
}

# 5. 监控进度
Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "📊 开始监控 Profile 更新进度..." -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "💡 提示: 按 Ctrl+C 可停止监控" -ForegroundColor Yellow
Write-Host ""

$checkCount = 0
$lastProcessed = 0
$stalledCount = 0

while ($true) {
    Start-Sleep -Seconds 10
    $checkCount++
    
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/api/profile/update-progress" `
            -UseBasicParsing `
            -TimeoutSec 5 `
            -ErrorAction Stop
        
        $progress = $response.Content | ConvertFrom-Json
        
        $isRunning = $progress.is_running
        $processed = $progress.processed
        $total = $progress.total_stocks
        $successful = $progress.successful
        $failed = $progress.failed
        $speed = if ($progress.speed_stocks_per_minute) { $progress.speed_stocks_per_minute } else { 0 }
        
        # 计算进度百分比
        if ($total -gt 0) {
            $percentage = ($processed / $total) * 100
        } else {
            $percentage = 0
        }
        
        # 进度条
        $barLength = 50
        $filled = [int]($barLength * $percentage / 100)
        $bar = "█" * $filled + "░" * ($barLength - $filled)
        
        Write-Host "[检查 #$checkCount] $bar $([math]::Round($percentage, 1))%" -ForegroundColor Cyan
        Write-Host "  已处理: $processed/$total | 成功: $successful | 失败: $failed | 速度: $([math]::Round($speed, 1)) 股/分钟" -ForegroundColor Gray
        
        # 检查是否卡住
        if ($processed -eq $lastProcessed) {
            $stalledCount++
            if ($stalledCount -gt 3) {
                Write-Host "⚠️ 进度似乎已停止 (连续 3 次无进展)" -ForegroundColor Yellow
            }
        } else {
            $stalledCount = 0
        }
        
        $lastProcessed = $processed
        
        # 检查是否完成
        if (-not $isRunning -and $processed -gt 0 -and $processed -eq $total) {
            Write-Host ""
            Write-Host "================================================================================" -ForegroundColor Green
            Write-Host "🎉 🎉 🎉 所有 Profile 更新已完成！🎉 🎉 🎉" -ForegroundColor Green
            Write-Host "================================================================================" -ForegroundColor Green
            Write-Host "✅ 总共更新: $processed 个股票" -ForegroundColor Green
            Write-Host "✅ 成功: $successful 个" -ForegroundColor Green
            Write-Host "❌ 失败: $failed 个" -ForegroundColor Green
            Write-Host "⏱️ 总耗时: $($checkCount * 10) 秒" -ForegroundColor Green
            Write-Host ""
            
            # 提示后续操作
            Write-Host "💡 后续操作:" -ForegroundColor Yellow
            Write-Host "   1. 访问前端查看最新数据: http://localhost:3000" -ForegroundColor Gray
            Write-Host "   2. 后端 API 文档: http://localhost:8000/docs" -ForegroundColor Gray
            Write-Host "   3. 关闭后端服务: 在后端窗口按 Ctrl+C" -ForegroundColor Gray
            Write-Host ""
            break
        }
        
    } catch {
        Write-Host "⚠️ 无法获取进度: $_" -ForegroundColor Yellow
    }
}
