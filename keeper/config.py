"""发送配置的读取与校验。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    """配置不合法时抛出。"""


@dataclass(frozen=True)
class Message:
    """一条候选消息：文字或抖音原生表情。"""

    type: str
    value: str

    @property
    def label(self) -> str:
        return self.value if self.type == "text" else f"[表情] {self.value}"


@dataclass(frozen=True)
class Sticker:
    """原生表情的定位信息。"""

    label: str
    category: str | None = None
    fallback_index: int | None = None


@dataclass(frozen=True)
class Config:
    friends: tuple[str, ...]
    messages: tuple[Message, ...]
    stickers: dict[str, Sticker]
    interval_min: float
    interval_max: float
    open_retries: int
    open_timeout: float

    @classmethod
    def from_mapping(cls, data: object) -> "Config":
        if not isinstance(data, dict):
            raise ConfigError("配置必须是一个 JSON 对象")

        friends = _string_list(data.get("friends"), "friends")
        messages = _message_list(data.get("messages"))
        stickers = _sticker_map(data.get("stickers"))

        for message in messages:
            if message.type == "sticker" and message.value not in stickers:
                raise ConfigError(
                    f"messages 里的表情「{message.value}」没有在 stickers 中定义定位信息"
                )

        interval = data.get("send_interval_seconds", {})
        if not isinstance(interval, dict):
            raise ConfigError("send_interval_seconds 必须是 {min, max} 对象")
        interval_min = _number(interval.get("min", 3), "send_interval_seconds.min")
        interval_max = _number(interval.get("max", 8), "send_interval_seconds.max")
        if interval_min < 0 or interval_max < interval_min:
            raise ConfigError("发送间隔必须满足 0 <= min <= max")

        retries = data.get("target_open_retries", 1)
        if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
            raise ConfigError("target_open_retries 必须是 >= 0 的整数")

        timeout = _number(data.get("target_open_timeout_seconds", 15), "target_open_timeout_seconds")
        if timeout <= 0:
            raise ConfigError("target_open_timeout_seconds 必须大于 0")

        return cls(
            friends=friends,
            messages=messages,
            stickers=stickers,
            interval_min=interval_min,
            interval_max=interval_max,
            open_retries=retries,
            open_timeout=timeout,
        )


def _string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{field} 必须是非空数组")
    items = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"{field}[{index}] 必须是非空字符串")
        items.append(item.strip())
    return tuple(items)


def _message_list(value: object) -> tuple[Message, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError("messages 必须是非空数组")
    messages = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            if not item.strip():
                raise ConfigError(f"messages[{index}] 必须是非空字符串")
            messages.append(Message("text", item.strip()))
            continue
        if not isinstance(item, dict):
            raise ConfigError(f"messages[{index}] 必须是字符串或 {{type, value}} 对象")
        kind = item.get("type", "text")
        if kind not in {"text", "sticker"}:
            raise ConfigError(f"messages[{index}].type 只能是 text 或 sticker")
        text = item.get("value")
        if not isinstance(text, str) or not text.strip():
            raise ConfigError(f"messages[{index}].value 必须是非空字符串")
        messages.append(Message(kind, text.strip()))
    return tuple(messages)


def _sticker_map(value: object) -> dict[str, Sticker]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError("stickers 必须是 {表情名: 定位信息} 对象")
    stickers = {}
    for name, item in value.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigError("stickers 的键必须是非空表情名")
        if not isinstance(item, dict):
            raise ConfigError(f"stickers[{name}] 必须是对象")
        category = item.get("category")
        if category is not None and not isinstance(category, str):
            raise ConfigError(f"stickers[{name}].category 必须是字符串")
        fallback = item.get("fallback_index")
        if fallback is not None and (
            isinstance(fallback, bool) or not isinstance(fallback, int) or fallback < 0
        ):
            raise ConfigError(f"stickers[{name}].fallback_index 必须是 >= 0 的整数")
        label = item.get("label", name)
        if not isinstance(label, str) or not label.strip():
            raise ConfigError(f"stickers[{name}].label 必须是非空字符串")
        stickers[name] = Sticker(
            label=label.strip(),
            category=category.strip() if isinstance(category, str) else None,
            fallback_index=fallback,
        )
    return stickers


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{field} 必须是数字")
    return float(value)


def load_config(path: str | Path | None = None) -> Config:
    """优先读环境变量 DOUYIN_CONFIG，其次读本地文件。"""
    raw = os.environ.get("DOUYIN_CONFIG", "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"DOUYIN_CONFIG 不是有效 JSON: {exc}") from exc
        return Config.from_mapping(data)

    target = Path(path or os.environ.get("CONFIG_PATH") or "config.json")
    if not target.exists():
        raise ConfigError(
            f"找不到配置文件 {target}。请复制 config.example.json 为 config.json，"
            "或设置 DOUYIN_CONFIG 环境变量。"
        )
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{target} 不是有效 JSON: {exc}") from exc
    return Config.from_mapping(data)
