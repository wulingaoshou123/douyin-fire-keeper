"""把配置、Cookie 和浏览器串起来，执行一次发送任务。"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

from .config import Config, Message
from .douyin import DouyinError, DouyinSession, LoginError, RiskError
from .notifier import notify

logger = logging.getLogger(__name__)


async def run(
    config: Config,
    cookies: list[dict],
    dry_run: bool,
    artifacts_dir: Path,
    headless: bool = True,
) -> dict:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {
        "mode": "dry-run" if dry_run else "send",
        "started_at": _now(),
        "finished_at": None,
        "fatal_error": None,
        "results": [],
    }

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        context = await browser.new_context(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1440, "height": 900},
        )
        await context.add_cookies(cookies)
        page = await context.new_page()

        try:
            session = DouyinSession(page, timeout_seconds=config.open_timeout)
            await session.wait_ready()
            await session.ensure_logged_in()
            logger.info("登录态有效，开始处理 %d 位好友", len(config.friends))

            for index, friend in enumerate(config.friends):
                if index > 0:
                    delay = random.uniform(config.interval_min, config.interval_max)
                    logger.info("等待 %.1f 秒后处理下一位好友", delay)
                    await asyncio.sleep(delay)
                result["results"].append(await _handle_friend(session, config, friend, dry_run, artifacts_dir))

        except LoginError as exc:
            result["fatal_error"] = f"登录失效：{exc}"
            logger.error(result["fatal_error"])
            await _screenshot(page, artifacts_dir, "login_failed")
        except RiskError as exc:
            result["fatal_error"] = f"触发安全验证：{exc}"
            logger.error(result["fatal_error"])
            await _screenshot(page, artifacts_dir, "risk_check")
        except Exception as exc:
            result["fatal_error"] = f"运行中断：{exc}"
            logger.exception("运行中断")
            await _screenshot(page, artifacts_dir, "fatal")
        finally:
            await context.close()
            await browser.close()

    result["finished_at"] = _now()
    result["ok"] = result["fatal_error"] is None and all(item["status"] != "failed" for item in result["results"])
    _write_result(artifacts_dir, result)
    try:
        await asyncio.to_thread(notify, result)
    except Exception as exc:
        logger.warning("通知发送异常：%s", exc)
    return result


async def _handle_friend(
    session: DouyinSession,
    config: Config,
    friend: str,
    dry_run: bool,
    artifacts_dir: Path,
) -> dict:
    entry: dict = {"friend": friend, "status": "failed", "message": None, "error": None}
    try:
        await session.open_friend(friend, retries=config.open_retries)
        if dry_run:
            entry["status"] = "verified"
            logger.info("[Dry Run] 已定位并打开好友「%s」，未发送消息", friend)
            return entry

        message = random.choice(config.messages)
        await _send_message(session, config, message)
        entry["status"] = "sent"
        entry["message"] = message.label
        entry["type"] = message.type
        logger.info("已向「%s」发送：%s", friend, message.label)
    except DouyinError as exc:
        entry["error"] = str(exc)
        logger.error("处理好友「%s」失败：%s", friend, exc)
        await _screenshot(session.page, artifacts_dir, f"friend_{_slug(friend)}")
    except Exception as exc:
        entry["error"] = f"未知错误：{exc}"
        logger.exception("处理好友「%s」时出错", friend)
        await _screenshot(session.page, artifacts_dir, f"friend_{_slug(friend)}")
    return entry


async def _send_message(session: DouyinSession, config: Config, message: Message) -> None:
    if message.type == "sticker":
        await session.send_sticker(config.stickers[message.value])
    else:
        await session.send_text(message.value)


async def _screenshot(page, artifacts_dir: Path, label: str) -> None:
    try:
        directory = artifacts_dir / "screenshots"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{_slug(label)}_{datetime.now().strftime('%H%M%S')}.png"
        await page.screenshot(path=str(path), full_page=False)
        logger.info("已保存截图：%s", path)
    except Exception as exc:
        logger.warning("保存截图失败：%s", exc)


def _write_result(artifacts_dir: Path, result: dict) -> None:
    try:
        path = artifacts_dir / "result.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("结果已写入：%s", path)
    except Exception as exc:
        logger.warning("写入 result.json 失败：%s", exc)


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", value).strip("_")
    return cleaned[:40] or "item"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
