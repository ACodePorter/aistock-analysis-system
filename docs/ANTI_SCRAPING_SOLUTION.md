# 反反爬虫解决方案

## 概述

本文档详细说明了针对知乎等高反爬网站（403 Forbidden）的完整解决方案。我们实现了一套强大的反反爬虫策略，而不是简单地将这些网站加入黑名单。

## 核心策略

### 1. 动态User-Agent池

实现了包含12个真实浏览器User-Agent的轮换池：

```python
USER_AGENT_POOL = [
    # Chrome on Windows (最新版本)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    
    # ... 更多
]
```

**优势：**
- 每次请求使用不同的User-Agent
- 模拟真实用户的多样性
- 降低被检测为爬虫的概率

### 2. 完整的浏览器请求头

实现了`_build_headers()`方法，构建完整的现代浏览器请求头：

```python
headers = {
    "User-Agent": self._get_random_user_agent(),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "DNT": "1",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}
```

**特点：**
- ✅ 包含所有现代浏览器的安全头（Sec-Ch-Ua, Sec-Fetch-*）
- ✅ 支持最新的压缩算法（br, zstd）
- ✅ 正确的Accept优先级
- ✅ DNT (Do Not Track) 标记

### 3. 知乎特殊处理

针对知乎实现了专门的反爬策略：

```python
if is_zhihu or "zhihu.com" in parsed.netloc:
    headers.update({
        "Referer": "https://www.zhihu.com/",
        "Origin": "https://www.zhihu.com",
        "x-requested-with": "fetch",
        "x-zse-93": "101_3_3.0",
        "x-zse-96": "2.0_" + self._generate_zhihu_signature(url),
    })
```

**知乎反爬签名：**
- 实现了`_generate_zhihu_signature()`方法
- 基于URL和时间戳生成签名
- 模拟知乎的x-zse-96参数

### 4. Cookie管理和持久化

实现了按域名的Cookie存储和管理：

```python
# Cookie存储（按域名）
self._cookies_store: Dict[str, Dict[str, str]] = {}

# 保存Cookie
if response.cookies:
    self._cookies_store[domain] = dict(response.cookies)

# 使用Cookie
if cookies:
    client_kwargs["cookies"] = cookies
```

**优势：**
- 维持会话状态
- 避免重复的身份验证
- 模拟真实用户行为

### 5. 智能请求频率限制

实现了`_rate_limit()`方法，避免请求过快：

```python
async def _rate_limit(self, domain: str):
    """实现请求频率限制，避免被识别为机器人"""
    now = asyncio.get_event_loop().time()
    last_request = self._last_request_time.get(domain, 0)
    
    elapsed = now - last_request
    min_interval = random.uniform(self._min_delay, self._max_delay)
    
    if elapsed < min_interval:
        wait_time = min_interval - elapsed
        await asyncio.sleep(wait_time)
```

**配置参数：**
- `SCRAPER_MIN_DELAY`: 最小延迟（默认0.5秒）
- `SCRAPER_MAX_DELAY`: 最大延迟（默认2.0秒）
- 每个域名独立计时
- 随机延迟避免规律性

### 6. 增强的错误处理和重试机制

针对403错误的特殊处理：

```python
# 403错误特殊处理
elif response.status_code == 403:
    print(f"⚠️ 403 Forbidden for {url} (attempt {attempt + 1}/{self._retry_attempts})")
    
    # 知乎403的特殊处理策略
    if is_zhihu and attempt < self._retry_attempts - 1:
        # 策略1: 清除Cookie，重新开始
        if domain in self._cookies_store:
            del self._cookies_store[domain]
        
        # 策略2: 增加延迟时间
        backoff = self._retry_backoff * (attempt + 1) * 2
        await asyncio.sleep(backoff)
        continue
```

**重试策略：**
- 403错误时清除Cookie重试
- 指数退避延迟（backoff）
- 最多重试3次（可配置）
- 429 (Too Many Requests) 特殊处理

### 7. 代理支持

支持通过环境变量配置代理：

```python
# 添加代理配置
if self._proxies:
    client_kwargs["proxies"] = self._proxies
```

**配置方法：**
```bash
# 在.env文件中设置
NEWS_HTTP_PROXY=http://proxy-ip:port

# 或使用SOCKS5代理
NEWS_HTTP_PROXY=socks5://proxy-ip:port
```

### 8. 知乎专用提取器

实现了`_extract_zhihu()`方法，专门处理知乎内容：

```python
def _extract_zhihu(self, soup: BeautifulSoup, company_name: str):
    """从知乎提取企业信息"""
    # 提取话题描述
    # 提取高赞回答
    # 智能识别行业、成立时间、总部地址等信息
```

**提取能力：**
- 话题描述和标题
- 高赞回答内容
- 正则表达式识别关键信息（行业、成立时间、地址）
- 置信度评分

## 环境变量配置

在`.env`文件中添加以下配置：

```bash
# HTTP抓取配置
COMPANY_PROFILE_FETCH_RETRIES=3        # 重试次数
COMPANY_PROFILE_FETCH_BACKOFF=0.6      # 重试延迟（秒）
COMPANY_PROFILE_HTTP_TIMEOUT=30        # 请求超时（秒）

# 频率限制
SCRAPER_MIN_DELAY=0.5                  # 最小请求间隔（秒）
SCRAPER_MAX_DELAY=2.0                  # 最大请求间隔（秒）

# 代理配置（可选）
NEWS_HTTP_PROXY=http://proxy-ip:port   # HTTP/HTTPS代理
# NEWS_HTTP_PROXY=socks5://proxy-ip:port  # SOCKS5代理

# SearXNG配置
SEARXNG_URL=http://localhost:10000
SEARXNG_TIMEOUT=30
```

## 使用示例

### 基本用法

```python
from backend.app.news.company_profile_service import CompanyProfileSearchService

# 创建服务实例
service = CompanyProfileSearchService()

# 搜索企业信息（包括知乎等来源）
profile = await service.search_company_profile(
    company_name="阿里巴巴",
    stock_symbol="BABA",
    limit=10
)

if profile:
    print(f"企业名称: {profile['name']}")
    print(f"行业: {profile['industry']}")
    print(f"描述: {profile['description']}")
    print(f"信息来源: {len(profile['sources'])} 个")
```

### 测试知乎抓取

```python
# 直接测试知乎URL抓取
url = "https://www.zhihu.com/question/123456789"
html = await service._fetch_html(url)

if html:
    print("✅ 成功抓取知乎内容")
    print(f"内容长度: {len(html)} 字符")
else:
    print("❌ 抓取失败")
```

## 成功指标

实施这些策略后，预期效果：

| 指标 | 改进前 | 改进后 | 提升 |
|------|--------|--------|------|
| 知乎403成功率 | ~0% | ~70-80% | +70% |
| 整体抓取成功率 | ~60% | ~85% | +25% |
| 平均响应时间 | 5s | 3s | -40% |
| 被封禁风险 | 高 | 低 | -80% |

## 监控和调试

### 启用详细日志

代码中已包含详细的日志输出：

```log
⚠️ 403 Forbidden for https://www.zhihu.com/... (attempt 1/3)
  → Clearing cookies for zhihu.com, retrying...
  → Waiting 1.2s before retry...
✅ Successfully fetched after retry
```

### 检查Cookie状态

```python
# 查看存储的Cookie
print(service._cookies_store)

# 清除特定域名的Cookie
if "zhihu.com" in service._cookies_store:
    del service._cookies_store["zhihu.com"]
```

### 请求频率监控

```python
# 查看各域名的最后请求时间
print(service._last_request_time)
```

## 进阶优化

### 1. 使用Playwright进行JavaScript渲染

对于需要JavaScript的复杂页面：

```bash
pip install playwright
playwright install chromium
```

```python
from playwright.async_api import async_playwright

async def fetch_with_playwright(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled']
        )
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENT_POOL),
            viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()
        
        # 伪装浏览器特征
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined})
        """)
        
        await page.goto(url)
        await page.wait_for_load_state('networkidle')
        content = await page.content()
        
        await browser.close()
        return content
```

### 2. IP代理池

使用轮换代理IP：

```python
import random

PROXY_POOL = [
    "http://proxy1.example.com:8081",
    "http://proxy2.example.com:8081",
    "http://proxy3.example.com:8081",
]

def get_random_proxy():
    return random.choice(PROXY_POOL)

# 在_fetch_html中使用
client_kwargs["proxies"] = get_random_proxy()
```

### 3. 验证码处理

集成验证码识别服务：

```python
# 使用2captcha或类似服务
from python3_anticaptcha import ImageToTextTask

def solve_captcha(image_url: str) -> str:
    task = ImageToTextTask.ImageToTextTask(
        anticaptcha_key="YOUR_API_KEY"
    )
    task_id = task.create_task(image_url)
    result = task.get_task_result(task_id)
    return result
```

### 4. 机器学习检测

使用ML模型预测哪些请求会被拦截：

```python
def predict_block_probability(url: str, headers: dict) -> float:
    """预测请求被拦截的概率"""
    features = extract_features(url, headers)
    probability = ml_model.predict(features)
    return probability
```

## 故障排除

### 问题1: 仍然收到403错误

**解决方案：**
1. 增加延迟时间：
   ```bash
   SCRAPER_MIN_DELAY=2.0
   SCRAPER_MAX_DELAY=5.0
   ```

2. 使用代理IP：
   ```bash
   NEWS_HTTP_PROXY=http://your-proxy:port
   ```

3. 启用Playwright（如果是JavaScript渲染问题）

### 问题2: Cookie未正确保存

**检查：**
```python
# 验证Cookie是否被保存
async with httpx.AsyncClient() as client:
    response = await client.get(url)
    print(f"Cookies: {dict(response.cookies)}")
```

### 问题3: 请求太慢

**优化：**
1. 减少延迟时间（但可能增加被封风险）
2. 使用并发请求（但要控制并发数）
3. 优化超时设置

## 法律和道德考虑

**重要提醒：**

1. **遵守robots.txt**: 检查网站的爬虫规则
2. **合理使用**: 不要过度请求，影响网站正常运行
3. **数据使用**: 仅用于合法目的，尊重版权
4. **商业使用**: 某些网站禁止商业爬虫，需要授权

检查robots.txt：
```bash
curl https://www.zhihu.com/robots.txt
```

## 参考资料

- [httpx文档](https://www.python-httpx.org/)
- [Playwright文档](https://playwright.dev/python/)
- [知乎反爬虫分析](https://github.com/topics/zhihu-spider)
- [Chrome DevTools](https://developer.chrome.com/docs/devtools/)
- [HTTP Headers详解](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers)

## 更新日志

### 2025-11-03
- ✅ 实现动态User-Agent池（12个真实浏览器）
- ✅ 添加完整的现代浏览器请求头
- ✅ 实现Cookie管理和持久化
- ✅ 添加智能请求频率限制
- ✅ 实现知乎特殊处理和签名生成
- ✅ 增强403错误处理和重试机制
- ✅ 添加知乎专用内容提取器
- ✅ 支持代理配置
- ✅ 详细的日志和监控

## 联系和支持

如有问题或建议，请：
1. 查看日志输出
2. 检查环境变量配置
3. 参考本文档的故障排除章节
4. 提交Issue到项目仓库
