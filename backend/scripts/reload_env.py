#!/usr/bin/env python3
"""
Qwen3 配置重新加载并运行诊断
"""

import os
import sys

# 强制重新加载 .env 配置
if os.path.exists(".env"):
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

# 现在检查配置
qwen_enabled = os.getenv("LOCAL_QWEN_ENABLED", "false").lower() in ("true", "1", "yes")
print(f"✓ 环境变量重新加载后 LOCAL_QWEN_ENABLED = {qwen_enabled}")
print(f"✓ LOCAL_QWEN_URL = {os.getenv('LOCAL_QWEN_URL', 'http://localhost:1234/v1')}")
print(f"✓ LOCAL_QWEN_MODEL = {os.getenv('LOCAL_QWEN_MODEL', 'local-model')}")

if qwen_enabled:
    print("\n✅ Qwen3 已启用！现在可以运行诊断...")
else:
    print("\n❌ Qwen3 仍然禁用，请检查 .env 文件")
    sys.exit(1)
