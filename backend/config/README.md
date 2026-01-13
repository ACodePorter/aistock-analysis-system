# 企业档案搜索服务配置管理系统

## 📋 概述

本系统提供了一个持久化的配置管理机制，用于管理企业档案搜索服务中的各种域名分类和规则。

## 🗂️ 文件结构

```
backend/
├── config/
│   └── company_profile_sources.json    # 配置文件（持久化存储）
├── app/
│   └── news/
│       ├── source_config_manager.py    # 配置管理器
│       └── company_profile_service.py  # 搜索服务（使用配置）
└── scripts/
    └── test_config_manager.py          # 测试脚本
```

## 📊 配置文件说明

### `backend/config/company_profile_sources.json`

包含以下配置类别：

### 1. **优先信源** (`preferred_sources`)

按优先级排序的可信信息来源，用于搜索结果排序。

```json
{
  "domain": "baike.baidu.com",
  "priority": 1,
  "name": "百度百科",
  "type": "encyclopedia",
  "reliability": "high",
  "notes": "权威、结构化、中文最全"
}
```

**字段说明**：
- `domain`: 域名
- `priority`: 优先级（数字越小优先级越高）
- `name`: 来源名称
- `type`: 类型（encyclopedia/business_registry/stock_exchange等）
- `reliability`: 可靠性（high/medium/low）
- `notes`: 备注说明

### 2. **黑名单** (`blocked_sources`)

必须排除的低质量或无关网站。

```json
{
  "domain": "guba.eastmoney.com",
  "reason": "股吧论坛",
  "category": "forum"
}
```

**字段说明**：
- `domain`: 域名
- `reason`: 屏蔽原因
- `category`: 分类（forum/low_quality/anti_scraping/app_store等）

### 3. **需要登录的网站** (`login_required_sources`)

检测到需要账号登录才能访问的网站，会自动跳过。

```json
{
  "domain": "qcc.com",
  "reason": "企查查需要登录查看详细信息",
  "detection_keywords": ["登录", "weblogin", "302 Found"],
  "added_at": "2025-11-03",
  "auto_detected": true
}
```

**字段说明**：
- `domain`: 域名
- `reason`: 检测原因
- `detection_keywords`: 检测关键词
- `added_at`: 添加时间
- `auto_detected`: 是否自动检测添加

### 4. **反爬虫严格的域名** (`strict_anti_scraping_domains`)

需要特殊反爬虫策略的网站。

```json
{
  "domain": "zhihu.com",
  "strategy": "cookie_rotation",
  "rate_limit_seconds": [2.0, 5.0],
  "notes": "需要清除cookies重试"
}
```

**字段说明**：
- `domain`: 域名
- `strategy`: 策略（special_headers/cookie_rotation/slow_rate）
- `rate_limit_seconds`: 延迟范围[最小, 最大]秒
- `notes`: 备注说明

### 5. **检测规则** (`detection_rules`)

自动检测登录页面和内容质量的规则。

```json
{
  "login_detection": {
    "enabled": true,
    "keywords": ["登录", "login", "会员帐户安全"],
    "http_status_codes": [302, 401, 403],
    "redirect_patterns": ["/login", "/weblogin"]
  }
}
```

## 🔧 使用方法

### 1. 基本使用

```python
from app.news.source_config_manager import get_config_manager

# 获取配置管理器（全局单例）
config = get_config_manager()

# 查询配置
preferred = config.get_preferred_sources()
blocked = config.get_blocked_sources()
login_required = config.get_login_required_sources()
strict_domains = config.get_strict_domains()
```

### 2. 域名判断

```python
# 检查是否在黑名单中
if config.is_blocked("guba.eastmoney.com"):
    print("该域名在黑名单中")

# 检查是否需要登录
if config.is_login_required("qcc.com"):
    print("该网站需要登录")

# 检查是否为反爬虫严格的域名
if config.is_strict_domain("zhihu.com"):
    info = config.get_strict_domain_info("zhihu.com")
    print(f"策略: {info['strategy']}, 延迟: {info['rate_limit_seconds']}")
```

### 3. 自动检测登录页面

```python
# 自动检测并添加需要登录的网站
html = "<html>请先登录查看详细信息</html>"
config.auto_add_login_required(
    url="https://example.com/page",
    html_content=html,
    status_code=302
)
```

### 4. 动态添加配置

```python
# 添加黑名单域名
config.add_blocked_source(
    domain="spam.example.com",
    reason="垃圾内容站点",
    category="low_quality"
)

# 添加需要登录的网站
config.add_login_required_source(
    domain="newsite.com",
    reason="检测到登录验证",
    detection_keywords=["登录", "验证"],
    auto_detected=True
)
```

### 5. 查看统计信息

```python
# 打印统计信息
config.print_stats()

# 获取统计数据
stats = config.get_stats()
print(f"优先信源: {stats['preferred_sources']}")
print(f"黑名单: {stats['blocked_sources']}")
print(f"需登录: {stats['login_required_sources']}")
print(f"严格域名: {stats['strict_domains']}")
```

## 🔄 集成到搜索服务

`CompanyProfileSearchService` 已自动集成配置管理器：

```python
# 初始化时自动加载配置
service = CompanyProfileSearchService()

# 服务会自动使用配置中的：
# - 优先信源列表进行结果排序
# - 黑名单过滤不相关网站
# - 登录检测跳过需要登录的页面
# - 严格域名应用特殊反爬虫策略
```

## 📝 自动检测功能

系统会在以下情况自动添加域名到配置：

### 1. **登录页面检测**

当检测到以下特征时，自动加入 `login_required_sources`：

- HTTP状态码：302, 401, 403
- URL包含：`/login`, `/weblogin`, `/signin`, `/auth`
- 内容包含关键词：
  - "登录"
  - "请先登录"
  - "会员帐户安全"
  - "需与您确认"
  - "验证码"
  - "captcha"

**示例日志**：
```
🔒 Detected login page for qcc.com
✅ Added qcc.com to login-required list: 检测到登录验证页面 (status=302): weblogin
```

### 2. **验证页面检测**

内容包含：
- "为提升会员帐户安全，我们需与您确认此网页操作行为确实出自您本人。"
- "请先登录查看详细信息"

## 🧪 测试

运行测试脚本验证配置：

```bash
cd backend/scripts
python test_config_manager.py
```

输出示例：
```
✅ Loaded source config from .../company_profile_sources.json

============================================================
📊 Source Configuration Stats
============================================================
  Preferred Sources:      13
  Blocked Sources:        11
  Login Required Sources: 4
  Strict Domains:         4
============================================================
```

## ⚙️ 环境变量

配置管理器支持以下环境变量（可选）：

```bash
# 配置文件路径（默认：backend/config/company_profile_sources.json）
COMPANY_PROFILE_CONFIG_PATH=/path/to/config.json

# 是否启用LLM筛选（默认：true）
COMPANY_PROFILE_ENABLE_LLM_FILTER=true
```

## 🔐 配置文件持久化

- 配置文件使用JSON格式，易于编辑和版本控制
- 所有动态添加的域名会自动保存到配置文件
- 支持热重载（修改配置文件后重启服务生效）
- 建议将配置文件加入版本控制（Git）

## 📈 配置维护建议

### 定期审查

1. **优先信源**：确保高质量信源排在前面
2. **黑名单**：删除误判的域名
3. **登录列表**：验证是否仍需登录
4. **严格域名**：调整反爬虫策略

### 手动编辑

可以直接编辑 `company_profile_sources.json` 文件：

```bash
# 备份
cp backend/config/company_profile_sources.json backend/config/company_profile_sources.json.bak

# 编辑
vim backend/config/company_profile_sources.json

# 重启服务生效
```

### 版本控制

```bash
# 提交配置更新
git add backend/config/company_profile_sources.json
git commit -m "Update source configuration: add new blocked domain"
git push
```

## 🛠️ 故障排除

### 配置文件不存在

```
⚠️ Config file not found: .../company_profile_sources.json, using defaults
✅ Saved source config to .../company_profile_sources.json
```

系统会自动创建默认配置文件。

### 配置加载失败

```
⚠️ Failed to load config: ..., using defaults
```

检查JSON格式是否正确，可以使用 [JSONLint](https://jsonlint.com/) 验证。

### 动态添加不生效

确保配置管理器有写入权限：

```bash
# 检查权限
ls -l backend/config/company_profile_sources.json

# 修改权限（如需要）
chmod 644 backend/config/company_profile_sources.json
```

## 📚 相关文档

- [企业档案搜索服务README](../app/news/README.md)
- [LLM筛选功能说明](../app/news/llm_processor.py)
- [反爬虫策略指南](../docs/anti_scraping.md)

## 🤝 贡献

欢迎提交配置改进建议：

1. Fork 项目
2. 修改 `company_profile_sources.json`
3. 测试验证
4. 提交 Pull Request

---

**维护人员**: AI Stock Analysis Team  
**最后更新**: 2025-11-03
