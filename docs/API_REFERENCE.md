# API 参考文档 - 公司画像系统

**版本**: 1.0  
**API 服务器**: `http://localhost:8081`

---

## 📚 目录

1. [概述](#概述)
2. [API 端点](#api-端点)
3. [错误处理](#错误处理)
4. [数据类型](#数据类型)
5. [代码示例](#代码示例)

---

## 概述

公司画像系统提供三个主要 API 端点，用于获取、分析和刷新股票的公司信息。

### 基础信息

- **基础 URL**: `http://localhost:8081`
- **认证**: 暂无（后续可添加）
- **速率限制**: 无
- **响应格式**: JSON
- **编码**: UTF-8

---

## API 端点

### 1. 获取基本 Profile 信息

#### 请求

```
GET /api/stock-profile/{symbol}
```

#### 参数

| 参数 | 类型 | 位置 | 必填 | 说明 |
|------|------|------|------|------|
| `symbol` | string | URL | ✅ | 股票代码，如 `000001.SZ` |

#### 返回成功响应

**状态码**: 200

```json
{
  "symbol": "000001.SZ",
  "company_name": "平安银行",
  "industry": "银行",
  "sub_industry": "商业银行",
  "business_summary": "平安银行是一家领先的商业银行，提供全面的金融服务...",
  "products": "个人理财,公司贷款,投资银行,资产管理",
  "competitors": "招商银行,工商银行,中国银行,建设银行",
  "risk_factors": "市场竞争,监管风险,利率风险,信用风险",
  "strategic_keywords": "金融服务,互联网+,数字化转型,普惠金融",
  "last_refreshed": "2025-10-17T10:30:00"
}
```

#### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `symbol` | string | 股票代码 |
| `company_name` | string | 公司名称 |
| `industry` | string | 行业分类 |
| `sub_industry` | string | 子行业分类 |
| `business_summary` | string | 业务介绍，长文本 |
| `products` | string | 产品列表，逗号分隔 |
| `competitors` | string | 竞争对手列表，逗号分隔 |
| `risk_factors` | string | 风险因素列表，逗号分隔 |
| `strategic_keywords` | string | 战略关键词，逗号分隔 |
| `last_refreshed` | datetime | 最后更新时间，ISO 8601 格式 |

#### 示例请求

```bash
# 使用 curl
curl http://localhost:8081/api/stock-profile/000001.SZ

# 使用 Python
import requests

response = requests.get(
  'http://localhost:8081/api/stock-profile/000001.SZ'
)
profile = response.json()
print(profile['company_name'])
```

---

### 2. 获取详细 Profile 信息（含分析数据）

#### 请求

```
GET /api/stock-profile/{symbol}/details
```

#### 参数

| 参数 | 类型 | 位置 | 必填 | 说明 |
|------|------|------|------|------|
| `symbol` | string | URL | ✅ | 股票代码 |

#### 返回成功响应

**状态码**: 200

```json
{
  "symbol": "000001.SZ",
  "company_name": "平安银行",
  "industry": "银行",
  "sub_industry": "商业银行",
  "business_summary": "...",
  "products": "个人理财,公司贷款,投资银行",
  "competitors": "招商银行,工商银行,中国银行",
  "risk_factors": "市场竞争,监管风险,利率风险",
  "strategic_keywords": "金融服务,互联网+,数字化转型",
  "last_refreshed": "2025-10-17T10:30:00",
  
  "analysis": {
    "profile_completeness": 85,
    "products_count": 3,
    "competitors_count": 3,
    "risk_factors_count": 3,
    "keywords_count": 3,
    "quality_score": 92,
    "data_sources": ["Company databases", "Public records"]
  },
  
  "industry_analysis": {
    "industry": "银行",
    "market_position": "Mid-market",
    "competition_level": 3
  }
}
```

#### 字段说明

基础字段同上，额外字段：

**analysis 对象**:

| 字段 | 类型 | 范围 | 说明 |
|------|------|------|------|
| `profile_completeness` | integer | 0-100 | 信息完整度百分比 |
| `products_count` | integer | 0+ | 产品列表中的产品数 |
| `competitors_count` | integer | 0+ | 竞争对手数 |
| `risk_factors_count` | integer | 0+ | 风险因素数 |
| `keywords_count` | integer | 0+ | 战略关键词数 |
| `quality_score` | integer | 50-100 | 信息质量评分 |
| `data_sources` | array | - | 数据来源列表 |

**industry_analysis 对象**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `industry` | string | 行业名称 |
| `market_position` | string | 市场位置（Niche/Mid-market/Leader） |
| `competition_level` | integer | 竞争激烈度（1-10） |

#### 示例请求

```bash
# 使用 curl
curl http://localhost:8081/api/stock-profile/000001.SZ/details

# 使用 Python
import requests
import json

response = requests.get(
  'http://localhost:8081/api/stock-profile/000001.SZ/details'
)
data = response.json()

print(f"完整度: {data['analysis']['profile_completeness']}%")
print(f"质量评分: {data['analysis']['quality_score']}")
print(f"市场地位: {data['industry_analysis']['market_position']}")
```

#### 计算公式

**完整度计算**:
```
completeness = (非空字段数 / 总字段数) × 100%
```

非空字段列表：
- company_name
- industry
- sub_industry
- business_summary
- products
- competitors
- risk_factors

**质量评分计算**:
```
quality_score = 50 + (completeness / 2)
```

- 最低分: 50（仅基础字段）
- 最高分: 100（所有字段完整）

---

### 3. 刷新 Profile 数据

#### 请求

```
POST /api/stock-profile/{symbol}/refresh
```

#### 参数

| 参数 | 类型 | 位置 | 必填 | 说明 |
|------|------|------|------|------|
| `symbol` | string | URL | ✅ | 股票代码 |

#### 请求体

无需请求体，仅需提供 URL 参数。

#### 返回成功响应

**状态码**: 200

```json
{
  "symbol": "000001.SZ",
  "company_name": "平安银行",
  "industry": "银行",
  "sub_industry": "商业银行",
  "business_summary": "...",
  "products": "...",
  "competitors": "...",
  "risk_factors": "...",
  "strategic_keywords": "...",
  "last_refreshed": "2025-10-17T14:30:00"
}
```

#### 说明

- **功能**: 触发 Profile 数据刷新过程
- **耗时**: 5-30 秒（取决于数据源）
- **副作用**: 更新 `last_refreshed` 时间戳
- **频率限制**: 建议不超过 1 次/分钟

#### 示例请求

```bash
# 使用 curl
curl -X POST http://localhost:8081/api/stock-profile/000001.SZ/refresh

# 使用 Python
import requests

response = requests.post(
  'http://localhost:8081/api/stock-profile/000001.SZ/refresh'
)
updated_profile = response.json()
print(f"更新时间: {updated_profile['last_refreshed']}")
```

---

## 错误处理

### 错误响应格式

```json
{
  "detail": "错误信息描述"
}
```

### HTTP 状态码

| 状态码 | 说明 | 常见原因 |
|--------|------|--------|
| 200 | 成功 | 请求成功 |
| 404 | 未找到 | 股票代码不存在或无对应 Profile |
| 500 | 服务器错误 | 后端处理失败 |

### 常见错误

#### 404 - Profile 未找到

```json
{
  "detail": "profile not found"
}
```

**原因**:
- 股票代码不存在
- 该股票的 Profile 数据未创建

**解决方案**:
1. 检查股票代码格式（如 000001.SZ）
2. 运行数据补充脚本 `build_stock_profiles.py`

#### 500 - 服务器错误

```json
{
  "detail": "Internal server error"
}
```

**原因**:
- 数据库连接失败
- 数据处理异常

**解决方案**:
1. 检查后端日志 `docker logs aistock-backend`
2. 检查数据库连接
3. 重启后端服务

### 错误处理示例

```typescript
// TypeScript/React 中的错误处理

async function fetchProfile(symbol: string) {
  try {
    const response = await fetch(
      `/api/stock-profile/${symbol}/details`
    );
    
    if (response.status === 404) {
      console.error('Profile 未找到');
      // 显示"暂无数据"提示
      return null;
    }
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const data = await response.json();
    return data;
    
  } catch (error) {
    console.error('获取 Profile 失败:', error);
    // 显示错误提示
    return null;
  }
}
```

---

## 数据类型

### StockProfile 对象

```typescript
interface StockProfile {
  // 基础字段
  symbol: string
  company_name: string
  industry: string
  sub_industry: string
  business_summary: string
  products: string        // 逗号分隔
  competitors: string     // 逗号分隔
  risk_factors: string    // 逗号分隔
  strategic_keywords: string  // 逗号分隔
  last_refreshed: string  // ISO 8601 格式
}
```

### Analysis 对象

```typescript
interface Analysis {
  profile_completeness: number  // 0-100
  products_count: number
  competitors_count: number
  risk_factors_count: number
  keywords_count: number
  quality_score: number  // 50-100
  data_sources: string[]
}
```

### IndustryAnalysis 对象

```typescript
interface IndustryAnalysis {
  industry: string
  market_position: string  // "Niche" | "Mid-market" | "Leader"
  competition_level: number  // 1-10
}
```

### 完整响应对象

```typescript
interface StockProfileDetailsResponse extends StockProfile {
  analysis: Analysis
  industry_analysis: IndustryAnalysis
}
```

---

## 代码示例

### JavaScript/TypeScript

#### 获取 Profile 列表

```typescript
async function getProfiles(symbols: string[]) {
  const profiles = await Promise.all(
    symbols.map(symbol =>
      fetch(`/api/stock-profile/${symbol}`)
        .then(r => r.json())
        .catch(() => null)
    )
  );
  return profiles.filter(Boolean);
}
```

#### 获取并显示详细信息

```typescript
async function displayProfileDetails(symbol: string) {
  const response = await fetch(
    `/api/stock-profile/${symbol}/details`
  );
  const profile = await response.json();
  
  console.log(`公司: ${profile.company_name}`);
  console.log(`行业: ${profile.industry}`);
  console.log(`完整度: ${profile.analysis.profile_completeness}%`);
  console.log(`质量评分: ${profile.analysis.quality_score}`);
}
```

#### 监听刷新操作

```typescript
async function refreshAndUpdate(symbol: string, callback: () => void) {
  try {
    const response = await fetch(
      `/api/stock-profile/${symbol}/refresh`,
      { method: 'POST' }
    );
    const updated = await response.json();
    console.log(`更新完成: ${updated.last_refreshed}`);
    callback();
  } catch (error) {
    console.error('刷新失败:', error);
  }
}
```

### Python

#### 获取 Profile

```python
import requests
from datetime import datetime

def get_profile(symbol: str) -> dict:
    """获取股票 Profile 信息"""
    url = f"http://localhost:8081/api/stock-profile/{symbol}"
    response = requests.get(url)
    
    if response.status_code == 404:
        print(f"Profile 未找到: {symbol}")
        return None
    
    response.raise_for_status()
    return response.json()

# 使用
profile = get_profile("000001.SZ")
if profile:
    print(f"公司: {profile['company_name']}")
    print(f"行业: {profile['industry']}")
```

#### 获取详细信息并分析

```python
def analyze_profile(symbol: str) -> dict:
    """获取并分析 Profile"""
    url = f"http://localhost:8081/api/stock-profile/{symbol}/details"
    response = requests.get(url)
    
    if not response.ok:
        return None
    
    data = response.json()
    analysis = data['analysis']
    
    return {
        'symbol': symbol,
        'company_name': data['company_name'],
        'completeness': f"{analysis['profile_completeness']}%",
        'quality_score': analysis['quality_score'],
        'products': analysis['products_count'],
        'competitors': analysis['competitors_count'],
        'market_position': data['industry_analysis']['market_position'],
    }

# 使用
result = analyze_profile("000001.SZ")
print(result)
```

#### 批量刷新 Profile

```python
def batch_refresh_profiles(symbols: list, interval: float = 1.0):
    """批量刷新 Profile，支持延迟"""
    import time
    
    results = []
    for symbol in symbols:
        try:
            url = f"http://localhost:8081/api/stock-profile/{symbol}/refresh"
            response = requests.post(url)
            response.raise_for_status()
            results.append((symbol, True, response.json()))
            print(f"✓ {symbol} 刷新成功")
        except Exception as e:
            results.append((symbol, False, str(e)))
            print(f"✗ {symbol} 刷新失败: {e}")
        
        time.sleep(interval)
    
    return results

# 使用
symbols = ['000001.SZ', '000723.SZ', '000858.SZ']
batch_refresh_profiles(symbols, interval=2.0)
```

### cURL

#### 获取基本 Profile

```bash
curl -X GET http://localhost:8081/api/stock-profile/000001.SZ
```

#### 获取详细 Profile

```bash
curl -X GET http://localhost:8081/api/stock-profile/000001.SZ/details \
  -H "Content-Type: application/json"
```

#### 刷新 Profile

```bash
curl -X POST http://localhost:8081/api/stock-profile/000001.SZ/refresh \
  -H "Content-Type: application/json"
```

#### 使用 jq 格式化输出

```bash
curl -s http://localhost:8081/api/stock-profile/000001.SZ/details | jq '.'

# 提取特定字段
curl -s http://localhost:8081/api/stock-profile/000001.SZ/details | \
  jq '.analysis | {completeness: .profile_completeness, quality: .quality_score}'
```

---

## 最佳实践

### ✅ 推荐做法

1. **添加错误处理**: 总是处理 404 和 500 错误
2. **缓存数据**: 短期缓存 Profile 数据以减少 API 调用
3. **异步加载**: 使用 async/await 或 Promise 避免阻塞
4. **限制刷新**: 刷新频率限制在 1 次/分钟以上

### ❌ 避免做法

1. 不要频繁调用刷新接口
2. 不要在同步代码中等待 API 响应
3. 不要忽视错误响应
4. 不要假设数据总是存在

---

**API 版本**: v1.0  
**最后更新**: 2025-10-17  
**下一版本**: v1.1 (预计 2025-10-31)

