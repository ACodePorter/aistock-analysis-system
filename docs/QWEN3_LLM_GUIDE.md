# Qwen3-4B 本地 LLM 使用指南

## 📋 概述

本项目现已支持通过 **LM Studio** 启动的本地 **Qwen3-4B** 模型作为 LLM 后端，可以在无网络、无 API Key 的情况下使用。

## 🚀 快速开始

### 1. 启动 LM Studio 和 Qwen3 模型

```bash
# 假设已安装 LM Studio
1. 打开 LM Studio 应用
2. 从模型库中搜索 "Qwen3-4B" 或 "Qwen 4B"
3. 点击下载并加载模型
4. LM Studio 会在默认端口 1234 启动 API 服务
```

**验证 LM Studio 是否启动**:
```bash
curl http://localhost:1234/v1/models
```

应该看到类似的响应：
```json
{
  "object": "list",
  "data": [
    {
      "id": "local-model",
      "object": "model",
      "created": 1234567890,
      "owned_by": "lm-studio"
    }
  ]
}
```

### 2. 配置 .env 文件

在项目根目录的 `.env` 文件中进行以下配置：

```properties
# 启用本地 Qwen3-4B
LOCAL_QWEN_ENABLED=true

# LM Studio API 端点
LOCAL_QWEN_URL=http://localhost:1234/v1

# 模型名称（LM Studio 默认为 local-model）
LOCAL_QWEN_MODEL=local-model

# HTTP 超时时间（秒，本地模型可能较慢）
LOCAL_QWEN_TIMEOUT=120

# 最大生成 token 数
LOCAL_QWEN_MAX_TOKENS=2048

# 生成参数
LOCAL_QWEN_TEMPERATURE=0.7    # 越低越确定，越高越随机
LOCAL_QWEN_TOP_P=0.9          # 词汇多样性控制

# 重试配置
LOCAL_QWEN_RETRY_TIMES=3      # 网络问题重试次数
LOCAL_QWEN_RETRY_DELAY=2      # 重试延迟（秒）
```

### 3. 测试 Qwen3 连接

运行测试脚本验证配置：

```bash
cd backend/scripts
python test_qwen3_llm.py
```

预期输出：
```
✅ 通过: 基本功能
✅ 通过: JSON 生成
✅ 通过: LLM 代理
✅ 通过: 提供商识别
✅ 通过: 系统提示词

📈 总体结果: 5/5 通过
🎉 所有测试通过！Qwen3-4B 已准备就绪
```

## 🔧 使用方法

### 方法 1: 直接使用 Qwen3 客户端

```python
import asyncio
from app.news.qwen_local_llm import get_qwen_client

async def main():
    client = get_qwen_client()
    
    # 生成文本
    result = await client.generate(
        prompt="请分析这条股票新闻...",
        max_tokens=256
    )
    print(result)
    
    # 生成 JSON
    json_result = await client.generate_json(
        prompt="请返回以下格式的 JSON: {sentiment: ..., companies: ...}"
    )
    print(json_result)

asyncio.run(main())
```

### 方法 2: 使用 LLM 服务代理（推荐）

LLM 服务代理会自动选择合适的后端：
- 优先使用本地 Qwen3-4B（如果启用）
- 其次使用 Azure OpenAI（如果配置）

```python
import asyncio
from app.news.llm_service_proxy import get_llm_service_proxy

async def main():
    proxy = get_llm_service_proxy()
    
    # 检查是否有可用的 LLM
    if not proxy.is_available():
        print("❌ 没有可用的 LLM")
        return
    
    print(f"使用 LLM: {proxy.get_provider_name()}")
    
    # 生成文本
    result = await proxy.generate(
        prompt="请分析...",
    )
    print(result)

asyncio.run(main())
```

### 方法 3: 快速接口

```python
import asyncio
from app.news.llm_service_proxy import generate_text, generate_json

async def main():
    # 生成文本
    text = await generate_text("请介绍一下你自己")
    print(text)
    
    # 生成 JSON
    data = await generate_json(
        "请返回 JSON: {name: ..., description: ...}"
    )
    print(data)

asyncio.run(main())
```

## 📊 性能参考

| 指标 | 值 |
|------|-----|
| 模型 | Qwen3-4B |
| 内存占用 | ~6-8 GB VRAM |
| 首个 token 延迟 | 500-2000 ms |
| 生成速度 | 10-20 tokens/s |
| 上下文长度 | 8192 tokens |
| 推荐超时时间 | 120-300 秒 |

*实际性能取决于硬件配置*

## 🛠️ 故障排除

### 问题 1: "连接被拒绝" 错误

```
❌ Qwen3 服务器不可用，请确保 LM Studio 正在运行
```

**解决方案**:
1. 确认 LM Studio 已启动
2. 检查模型是否已加载
3. 验证端口 1234 是否开放
4. 检查防火墙设置

### 问题 2: "请求超时"

```
⚠️ Qwen3 服务器连接超时 (120s)
```

**解决方案**:
1. 增加 `LOCAL_QWEN_TIMEOUT` 值（如 300 秒）
2. 检查硬件资源（CPU/内存）
3. 尝试减小 `LOCAL_QWEN_MAX_TOKENS`
4. 重启 LM Studio

### 问题 3: "生成文本为空"

**解决方案**:
1. 检查提示词是否正确
2. 增加 `LOCAL_QWEN_MAX_TOKENS`
3. 在 LM Studio 中手动测试
4. 查看 LM Studio 的错误日志

### 问题 4: JSON 解析失败

**解决方案**:
1. 在提示词中明确要求返回有效的 JSON
2. 使用 `generate_json()` 方法而不是 `generate()`
3. 增加 `max_tokens` 给予模型更多空间
4. 调整 `temperature` 为更低的值（如 0.3）

## 🔄 与 Azure OpenAI 的切换

该系统支持自动切换 LLM 后端：

### 只使用本地 Qwen3
```properties
LOCAL_QWEN_ENABLED=true
# 不配置 AZURE_OPENAI_ENDPOINT 和 AZURE_OPENAI_KEY
```

### 只使用 Azure OpenAI
```properties
LOCAL_QWEN_ENABLED=false
AZURE_OPENAI_ENDPOINT=https://your-endpoint.openai.azure.com
AZURE_OPENAI_KEY=your-key
```

### 自动切换（优先使用本地 Qwen）
```properties
LOCAL_QWEN_ENABLED=true
AZURE_OPENAI_ENDPOINT=https://your-endpoint.openai.azure.com  # 备用
AZURE_OPENAI_KEY=your-key  # 备用
```

## 📈 监控和日志

### 查看 Qwen3 调用日志

日志会记录到文件：
```
logs/update_stock_profiles.log
```

典型的日志输出：
```
2025-01-10 10:30:45 - app.news.qwen_local_llm - INFO - ✅ Qwen3-4B 本地 LLM 客户端初始化完成
2025-01-10 10:30:45 - app.news.qwen_local_llm - INFO -    启用状态: ✅ 已启用
2025-01-10 10:30:46 - app.news.qwen_local_llm - INFO - ✅ Qwen3 生成成功 (尝试 1/3)
```

### 启用调试日志

在 `.env` 中修改：
```properties
LOG_LEVEL=DEBUG
```

## 🎯 最佳实践

### 1. 生成提示词

**好的提示词**:
```python
prompt = """分析以下股票新闻并提取关键信息。

新闻标题: 阿里巴巴发布新产品
新闻内容: ...

请返回 JSON 格式: {
    "summary": "...",
    "companies": [...],
    "sentiment": "positive|neutral|negative"
}"""
```

**避免**:
- 过于简短或模糊的提示词
- 要求多个复杂任务
- 期望完全准确的输出（本地模型 ≠ GPT-4）

### 2. 参数调优

```python
# 创意写作
await client.generate(
    prompt="...",
    temperature=0.8,  # 较高，更随机
    top_p=0.95
)

# 严格分析
await client.generate(
    prompt="...",
    temperature=0.3,  # 较低，更确定
    top_p=0.7
)

# JSON 生成
await client.generate_json(
    prompt="...",
    temperature=0.1,  # 最低，最稳定
)
```

### 3. 错误处理

```python
try:
    result = await client.generate(prompt)
    if result:
        print(f"✅ 成功: {result}")
    else:
        print("❌ 生成为空")
except Exception as e:
    print(f"❌ 异常: {e}")
```

## 📚 相关文件

- **主要实现**: `backend/app/news/qwen_local_llm.py`
- **服务代理**: `backend/app/news/llm_service_proxy.py`
- **测试脚本**: `backend/scripts/test_qwen3_llm.py`
- **配置**: `.env` 中的 `LOCAL_QWEN_*` 相关变量

## ⚙️ 文件清单

```
backend/
├── app/
│   └── news/
│       ├── qwen_local_llm.py       # Qwen3 客户端实现
│       ├── llm_service_proxy.py    # LLM 服务代理
│       └── llm_processor.py        # 现有 LLM 处理器
└── scripts/
    └── test_qwen3_llm.py           # 测试脚本

.env                                 # 配置文件（已更新）
```

## 🔗 相关资源

- [LM Studio](https://lmstudio.ai/) - 本地 LLM 运行工具
- [Qwen 官方文档](https://qwenlm.github.io/)
- [OpenAI API 兼容性](https://github.com/lmstudio-ai/lm-studio)

## 💡 常见问题

**Q: Qwen3-4B 需要多少显存？**
A: 约 6-8 GB VRAM。可以用 `-ngl` 参数调整。

**Q: 可以使用其他本地模型吗？**
A: 可以！只要支持 OpenAI 兼容 API（如 LLaMA、Mistral 等）。

**Q: 如何离线使用？**
A: 确保 LM Studio 已启动模型，网络连接只需要 localhost。

**Q: 生成质量与 GPT-4 相比？**
A: Qwen3-4B 是轻量级模型，适合日常任务，但在复杂推理上不如 GPT-4。

## 📝 变更日志

### v1.0 (2025-01-10)
- ✅ 实现 Qwen3LocalLLMClient
- ✅ 创建 LLM 服务代理
- ✅ 添加自动提供商切换
- ✅ 完整的测试套件
- ✅ 重试和超时机制
