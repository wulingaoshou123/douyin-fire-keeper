"""任务结果通知：钉钉机器人、通用 Webhook（飞书/企业微信/Slack 等）。"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


def notify(result: dict) -> None:
    """按环境变量配置发送通知；未配置则静默跳过，失败不影响主流程。"""
    try:
        _dingtalk(result)
        _webhook(result)
    except Exception as exc:
        logger.warning("发送通知失败（不影响任务结果）：%s", exc)


def _dingtalk(result: dict) -> None:
    webhook = os.environ.get("DINGTALK_WEBHOOK", "").strip()
    if not webhook:
        return
    secret = os.environ.get("DINGTALK_SECRET", "").strip()
    url = webhook
    if secret:
        timestamp = str(round(time.time() * 1000))
        sign = _dingtalk_sign(timestamp, secret)
        url = f"{webhook}&timestamp={timestamp}&sign={sign}"
    _post(url, {"msgtype": "text", "text": {"content": _summary(result)}}, "钉钉")


def _webhook(result: dict) -> None:
    url = os.environ.get("WEBHOOK_URL", "").strip()
    if not url:
        return

    template = os.environ.get("WEBHOOK_TEMPLATE", "").strip()
    payload = _render_template(template, result) if template else {"text": _summary(result)}

    headers = {"Content-Type": "application/json"}
    extra = os.environ.get("WEBHOOK_HEADERS", "").strip()
    if extra:
        try:
            parsed = json.loads(extra)
            if isinstance(parsed, dict):
                headers.update({str(k): str(v) for k, v in parsed.items()})
        except json.JSONDecodeError as exc:
            logger.warning("WEBHOOK_HEADERS 不是有效 JSON，已忽略：%s", exc)

    _post(url, payload, "Webhook", headers)


def _render_template(template: str, result: dict) -> dict:
    """把 {占位符} 替换成实际值，返回解析后的 JSON。"""
    context = _template_context(result)
    # 逐键替换，避免 json 里的大括号被 str.format 误判
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace("{" + key + "}", value)
    try:
        return json.loads(rendered)
    except json.JSONDecodeError:
        logger.warning("WEBHOOK_TEMPLATE 替换后不是有效 JSON，改用默认格式")
        return {"text": _summary(result)}


def _template_context(result: dict) -> dict[str, str]:
    results = result.get("results", [])
    success = sum(1 for item in results if item["status"] in {"sent", "verified"})
    failed = sum(1 for item in results if item["status"] == "failed")
    status = "全部成功" if failed == 0 and not result.get("fatal_error") else "存在失败"
    return {
        "status": status,
        "mode": "检查模式" if result.get("mode") == "dry-run" else "正式发送",
        "success_count": str(success),
        "failed_count": str(failed),
        "total_count": str(len(results)),
        "timestamp": result.get("finished_at") or "",
        "results_json": json.dumps(results, ensure_ascii=False),
    }


def _summary(result: dict) -> str:
    context = _template_context(result)
    lines = [
        "🔥 抖音续火花任务",
        f"模式：{context['mode']}",
        f"状态：{context['status']}",
        f"成功 {context['success_count']} / 失败 {context['failed_count']} / 共 {context['total_count']}",
    ]
    if result.get("fatal_error"):
        lines.append(f"错误：{result['fatal_error']}")
    for item in result.get("results", []):
        if item["status"] == "sent":
            lines.append(f"✅ {item['friend']}：{item['message']}")
        elif item["status"] == "verified":
            lines.append(f"🔎 {item['friend']}：可定位（未发送）")
        else:
            lines.append(f"❌ {item['friend']}：{item['error']}")
    return "\n".join(lines)


def _dingtalk_sign(timestamp: str, secret: str) -> str:
    import base64
    import hashlib
    import hmac

    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha256).digest()
    return quote_plus(base64.b64encode(digest))


def _post(url: str, payload: dict, label: str, headers: dict | None = None) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    with urllib.request.urlopen(request, timeout=15) as response:
        if 200 <= response.status < 300:
            logger.info("%s 通知已发送", label)
        else:
            logger.warning("%s 通知返回状态码 %s", label, response.status)
