"""把 Cookie-Editor 导出的 JSON 转换成 Playwright 需要的格式。"""

from __future__ import annotations

import json
import os
from pathlib import Path


class CookieError(ValueError):
    """Cookie 内容不合法时抛出。"""


_SAME_SITE = {
    "no_restriction": "None",
    "none": "None",
    "lax": "Lax",
    "strict": "Strict",
}


def parse_cookies(raw: str) -> list[dict]:
    """解析 Cookie 数组。

    支持 Cookie-Editor 的完整 JSON 导出，也支持只保留 name/value 的精简数组。
    """
    text = (raw or "").strip()
    if not text:
        raise CookieError("Cookie 内容为空")
    if text.startswith("name=value"):
        raise CookieError("这是浏览器请求头格式，请改用 Cookie-Editor 导出的 JSON 数组")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CookieError(f"Cookie 不是有效 JSON: {exc}") from exc

    if isinstance(data, dict) and isinstance(data.get("cookies"), list):
        data = data["cookies"]
    if not isinstance(data, list) or not data:
        raise CookieError("Cookie 必须是 JSON 数组，例如 [{...}, {...}]")

    cookies = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise CookieError(f"Cookie[{index}] 必须是对象")
        name = item.get("name")
        value = item.get("value")
        if not isinstance(name, str) or not name:
            raise CookieError(f"Cookie[{index}] 缺少 name")
        if not isinstance(value, str):
            raise CookieError(f"Cookie[{index}] 缺少 value")

        cookie = {
            "name": name,
            "value": value,
            "domain": item.get("domain") or ".douyin.com",
            "path": item.get("path") or "/",
        }
        expires = _expires(item)
        if expires is not None:
            cookie["expires"] = expires
        if isinstance(item.get("httpOnly"), bool):
            cookie["httpOnly"] = item["httpOnly"]
        if isinstance(item.get("secure"), bool):
            cookie["secure"] = item["secure"]
        same_site = _same_site(item.get("sameSite"))
        if same_site:
            cookie["sameSite"] = same_site
            if same_site == "None":
                # Playwright 要求 SameSite=None 的 Cookie 必须带 Secure
                cookie["secure"] = True
        cookies.append(cookie)

    if not any("douyin.com" in c["domain"] for c in cookies):
        raise CookieError("Cookie 里没有任何 douyin.com 域的条目，请确认是在抖音网页版导出")
    if not any(c["name"] in {"sessionid", "sessionid_ss", "sid_tt"} for c in cookies):
        raise CookieError("Cookie 里没有 sessionid，登录态可能未生效，请重新登录抖音后导出")
    return cookies


def _expires(item: dict) -> int | None:
    if item.get("session") is True:
        return -1
    for key in ("expirationDate", "expires", "expiry"):
        value = item.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    return None


def _same_site(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return _SAME_SITE.get(value.strip().lower())


def load_cookies(path: str | Path | None = None) -> list[dict]:
    """优先读环境变量 DOUYIN_COOKIE，其次读本地文件。"""
    raw = os.environ.get("DOUYIN_COOKIE", "")
    if raw.strip():
        return parse_cookies(raw)

    target = Path(path or os.environ.get("COOKIE_PATH") or "cookies.json")
    if not target.exists():
        raise CookieError(
            f"找不到 Cookie 文件 {target}。请用 Cookie-Editor 导出 JSON 保存为该文件，"
            "或设置 DOUYIN_COOKIE 环境变量。"
        )
    return parse_cookies(target.read_text(encoding="utf-8"))
