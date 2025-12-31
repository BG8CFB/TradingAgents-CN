# 股票筛选 API 测试
$ErrorActionPreference = "Stop"
$BASE_URL = "http://localhost:3000"

Write-Host "`n=== 测试 1: 登录 ===" -ForegroundColor Cyan
$loginBody = @{
    username = "admin"
    password = "admin123"
} | ConvertTo-Json

try {
    $loginResp = Invoke-RestMethod -Uri "$BASE_URL/api/auth/login" -Method POST -Body $loginBody -ContentType "application/json"
    $token = $loginResp.data.token
    Write-Host "✓ 登录成功" -ForegroundColor Green
    Write-Host "  Token: $($token.Substring(0, [Math]::Min(50, $token.Length)))..." -ForegroundColor Gray
} catch {
    Write-Host "✗ 登录失败: $_" -ForegroundColor Red
    exit 1
}

Write-Host "`n=== 测试 2: 获取字段配置 ===" -ForegroundColor Cyan
try {
    $fieldsResp = Invoke-RestMethod -Uri "$BASE_URL/api/screening/fields" -Method GET
    $fieldCount = ($fieldsResp.fields.PSObject.Properties.Name | Measure-Object).Count
    Write-Host "✓ 获取字段配置成功: $fieldCount 个字段" -ForegroundColor Green
} catch {
    Write-Host "✗ 获取字段配置失败: $_" -ForegroundColor Red
}

Write-Host "`n=== 测试 3: 获取行业列表 ===" -ForegroundColor Cyan
try {
    $industriesResp = Invoke-RestMethod -Uri "$BASE_URL/api/screening/industries" -Method GET
    $industries = $industriesResp.industries
    $total = $industriesResp.total
    $source = $industriesResp.source

    Write-Host "✓ 获取行业列表成功: $total 个行业, 来源: $source" -ForegroundColor Green

    if ($industries -and $industries.Count -gt 0) {
        Write-Host "  前3个行业:" -ForegroundColor Yellow
        $industries | Select-Object -First 3 | ForEach-Object {
            Write-Host "    - $($_.label) ($($_.count) 只股票)" -ForegroundColor Gray
        }
    } else {
        Write-Host "  警告: 行业列表为空" -ForegroundColor Yellow
    }
} catch {
    Write-Host "✗ 获取行业列表失败: $_" -ForegroundColor Red
}

Write-Host "`n=== 测试 4: 简单筛选 ===" -ForegroundColor Cyan
$payload = @{
    market = "CN"
    date = $null
    adj = "qfq"
    conditions = @{
        logic = "AND"
        children = @()
    }
    order_by = @(
        @{ field = "total_mv"; direction = "desc" }
    )
    limit = 10
    offset = 0
} | ConvertTo-Json -Depth 10

$headers = @{
    "Authorization" = "Bearer $token"
    "Content-Type" = "application/json"
}

try {
    $screenResp = Invoke-RestMethod -Uri "$BASE_URL/api/screening/run" -Method POST -Body $payload -Headers $headers -TimeoutSec 120
    $total = $screenResp.total
    $items = $screenResp.items

    Write-Host "✓ 筛选成功: 返回 $total 只股票, 显示前 $($items.Count) 只" -ForegroundColor Green

    if ($items -and $items.Count -gt 0) {
        Write-Host "  前3只股票:" -ForegroundColor Yellow
        $items | Select-Object -First 3 | ForEach-Object {
            $code = $_.code
            $name = $_.name
            $marketCap = if ($_.total_mv) { "{0:N2}" -f $_.total_mv } else { "N/A" }
            Write-Host "    - $code $name`: 市值 $marketCap 亿" -ForegroundColor Gray
        }
    } else {
        Write-Host "  警告: 没有筛选到任何股票" -ForegroundColor Yellow
        Write-Host "  可能原因: 数据库中没有股票数据，需要先同步数据" -ForegroundColor Yellow
    }
} catch {
    Write-Host "✗ 筛选失败: $_" -ForegroundColor Red
    Write-Host "  响应状态: $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Gray
}

Write-Host "`n=== 测试完成 ===" -ForegroundColor Cyan
