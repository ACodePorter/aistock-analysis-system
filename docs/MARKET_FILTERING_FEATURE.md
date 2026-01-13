## 股票市场标签化与过滤功能实现总结

### 功能概述
已实现对股票进行市场标签化（A股、港股、美股），并在股票资讯页面添加市场筛选器，默认显示A股数据。

---

### 后端实现

#### 1. **数据模型更新** (`backend/app/models.py`)
- 给 `StockProfile` 模型添加了 `market` 字段：
  ```python
  market: Mapped[str] = mapped_column(String(16), default="A股", nullable=False, index=True, comment="市场标签：A股/港股/美股/新股等")
  ```
  - 默认值：`"A股"`
  - 有索引，支持高效过滤

#### 2. **自动数据库迁移** (`backend/app/db.py`)
- 在应用启动时（`init_database()`）自动添加 `market` 字段：
  - 检查列是否存在，若不存在则自动添加
  - 自动识别并填充市场信息：
    - `.HK` 后缀 → `港股`
    - 纯英文代码 → `美股`
    - 其他 → `A股`
  ```sql
  UPDATE stock_profiles
  SET market = CASE
      WHEN symbol ILIKE '%.HK' THEN '港股'
      WHEN symbol ~ '^[A-Z]+$' THEN '美股'
      ELSE 'A股'
  END
  ```

#### 3. **API 端点更新** (`backend/app/main.py`)
- 修改 `/api/news/stocks/progress` 端点，添加市场过滤参数：
  ```python
  @app.get("/api/news/stocks/progress")
  async def get_stocks_update_progress(
      page: int = Query(1, ge=1),
      page_size: int = Query(20, ge=1, le=100),
      show_invalid: bool = Query(False),
      q: str = Query(None),
      market: str = Query("A股", description="股票市场过滤：A股/港股/美股/全部"),
      db: Session = Depends(get_db)
  ):
  ```
  - 参数说明：
    - `market="A股"`：默认过滤A股
    - `market="全部"`：显示所有市场的股票
    - `market="港股"`、`market="美股"`：分别显示港股和美股

- 后端过滤逻辑：
  ```python
  if market != "全部" and profile.market != market:
      continue
  ```

---

### 前端实现

#### 1. **组件状态更新** (`frontend/src/ui/StocksNewsIndex.tsx`)
- 添加市场状态变量，默认 A股：
  ```typescript
  const [market, setMarket] = React.useState('A股')
```

#### 2. **市场选择器 UI**
- 在搜索框和过滤器旁添加市场下拉选择器：
  ```tsx
  <select 
    value={market}
    onChange={(e) => {
      setMarket(e.target.value)
      setTimeout(() => load(true), 100)
    }}
    style={{...样式...}}
  >
    <option value="A股">📍 A股</option>
    <option value="港股">🇭🇰 港股</option>
    <option value="美股">🇺🇸 美股</option>
    <option value="全部">🌍 全部市场</option>
  </select>
  ```
  - 选择器包含表情符号标识各市场
  - 颜色：蓝色背景，表示主要过滤器
  - 切换市场后自动重新加载数据

#### 3. **API 集成更新**
- 在 `load()` 函数中传递市场参数：
  ```typescript
  const firstPageUrl = buildApiUrl(`/api/news/stocks/progress?page=1&page_size=100&show_invalid=${showInvalid}&market=${encodeURIComponent(market)}`)
  ```
- 在 `loadRemainingPages()` 中也传递市场参数以保证后台加载的所有页面都符合过滤条件

#### 4. **依赖关系更新**
- `load()` 函数的依赖数组包含 `market`：
  ```typescript
  [showInvalid, q, market]
  ```
  - 当市场改变时，自动重新加载数据

---

### 使用流程

1. **默认显示 A股**
   - 打开股票资讯页面时，下拉选择器默认显示 "📍 A股"
   - 列表自动加载 A股数据

2. **切换市场**
   - 用户选择其他市场（港股、美股、全部）
   - 页面立即发起新 API 请求
   - 表格重新加载对应市场的数据

3. **搜索与市场过滤并行**
   - 市场过滤和搜索框 (q 参数) 可同时使用
   - 优先级：市场过滤 → 搜索词过滤

4. **无效 Profile 与市场过滤并行**
   - `show_invalid` 和 `market` 参数独立工作
   - 两个都为真时，显示该市场中所有有效和无效 Profile

---

### 数据库字段示例

| symbol | market | company_name | is_valid |
|--------|--------|--------------|----------|
| 600519.SH | A股 | 贵州茅台 | true |
| 0700.HK | 港股 | 腾讯控股 | true |
| AAPL | 美股 | Apple Inc. | true |
| TSLA | 美股 | Tesla Inc. | true |

---

### 测试要点

- [ ] 应用启动时自动添加 `market` 字段（检查数据库日志）
- [ ] 默认显示 A股数据
- [ ] 切换到港股、美股、全部时正确过滤
- [ ] 搜索框与市场过滤结合使用
- [ ] 分页加载时保持市场过滤条件
- [ ] 前后端市场常数保持一致（"A股"、"港股"、"美股"、"全部"）

---

### 文件清单

| 文件 | 修改内容 |
|------|---------|
| `backend/app/models.py` | 添加 `StockProfile.market` 字段 |
| `backend/app/db.py` | 添加自动迁移逻辑 |
| `backend/app/main.py` | 添加 `market` 查询参数和过滤逻辑 |
| `frontend/src/ui/StocksNewsIndex.tsx` | 添加市场选择器 UI、状态、API 集成 |

---

### 下一步优化方向

- [ ] 添加市场统计显示（各市场股票数量）
- [ ] 记住用户最后选择的市场（localStorage）
- [ ] 支持多市场同时选择
- [ ] 添加新市场时的动态配置机制
