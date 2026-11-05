#!/usr/bin/env python3
"""命令行入口：发送、Dry Run、页面结构诊断。"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from keeper.config import ConfigError, load_config
from keeper.cookies import CookieError, load_cookies
from keeper.douyin import DouyinSession
from keeper.runner import run

ARTIFACTS_DIR = Path("artifacts")
logger = logging.getLogger("keeper")


def setup_logging() -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = logging.FileHandler(ARTIFACTS_DIR / "run.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[console, file_handler])


async def diagnose(cookies: list[dict], headless: bool) -> int:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        context = await browser.new_context(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1440, "height": 900},
        )
        await context.add_cookies(cookies)
        page = await context.new_page()
        session = DouyinSession(page)
        await session.wait_ready()

        report = await session.diagnose()
        print(json.dumps(report, ensure_ascii=False, indent=2))

        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(ARTIFACTS_DIR / "diagnose.png"))
        print(f"\n页面截图已保存：{ARTIFACTS_DIR / 'diagnose.png'}")
        print("每一项后面列出的是当前命中的选择器；如果某一项为空，说明该选择器需要更新。")

        await context.close()
        await browser.close()
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description="抖音自动续火花")
    parser.add_argument("--dry-run", action="store_true", help="只验证登录和好友，不发送消息")
    parser.add_argument("--diagnose", action="store_true", help="输出各关键选择器的命中情况并截图")
    parser.add_argument("--config", help="配置文件路径，默认 config.json")
    parser.add_argument("--cookie-file", help="Cookie JSON 路径，默认 cookies.json")
    parser.add_argument("--show", action="store_true", help="显示浏览器窗口，便于本地观察")
    args = parser.parse_args()

    setup_logging()
    headless = not args.show

    try:
        cookies = load_cookies(args.cookie_file)
    except CookieError as exc:
        logger.error("Cookie 读取失败：%s", exc)
        return 2

    if args.diagnose:
        return await diagnose(cookies, headless)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        logger.error("配置读取失败：%s", exc)
        return 2

    result = await run(config, cookies, args.dry_run, ARTIFACTS_DIR, headless=headless)

    print()
    print("=" * 52)
    for item in result["results"]:
        if item["status"] == "sent":
            print(f"✅ {item['friend']}：已发送「{item['message']}」")
        elif item["status"] == "verified":
            print(f"🔎 {item['friend']}：登录有效、好友可定位（Dry Run 未发送）")
        else:
            print(f"❌ {item['friend']}：{item['error']}")
    if result["fatal_error"]:
        print(f"⛔ {result['fatal_error']}")
    print("=" * 52)
    print(f"模式：{result['mode']}　结果：{'成功' if result['ok'] else '失败'}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
