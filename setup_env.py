#!/usr/bin/env python3
"""设置环境配置文件脚本
如果 .env 文件不存在，则从示例文件创建
"""
from pathlib import Path
import shutil

def setup_env():
    env_file = Path(".env")
    example_file = Path("config/env.example")
    
    if env_file.exists():
        print(".env 文件已存在，跳过创建。")
        print("如果遇到配置错误，请检查 .env 文件中的 BOT_TOKEN 是否已正确设置。")
        return
    
    if not example_file.exists():
        print(f"错误：找不到示例文件 {example_file}")
        return
    
    # 复制示例文件
    shutil.copy(example_file, env_file)
    print("已创建 .env 文件！")
    print()
    print("请编辑 .env 文件，设置你的 BOT_TOKEN：")
    print("1. 打开 .env 文件")
    print("2. 将 YOUR_TELEGRAM_BOT_TOKEN 替换为你的实际机器人令牌")
    print()
    print("如何获取 BOT_TOKEN：")
    print("1. 在 Telegram 中搜索 @BotFather")
    print("2. 发送 /newbot 命令创建新机器人")
    print("3. 按照提示完成创建后，BotFather 会提供 BOT_TOKEN")

if __name__ == "__main__":
    setup_env()

