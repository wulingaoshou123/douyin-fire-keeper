"""抖音私信页面的登录检查、好友定位与消息发送。"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from playwright.async_api import Locator, Page

from .config import Sticker

logger = logging.getLogger(__name__)

CHAT_URL = "https://www.douyin.com/chat"

# 以下选择器来自抖音网页版的实际结构，页面改版时只需调整这里。
SEARCH_INPUTS = (
    'input[placeholder*="搜索"]',
    '[role="textbox"][placeholder*="搜索"]',
    'input[aria-label*="搜索"]',
    '[role="textbox"][aria-label*="搜索"]',
)
LOGIN_REQUIRED = (
    "text=扫码登录",
    "text=验证码登录",
    "text=登录后",
)
RISK_REQUIRED = (
    "text=安全验证",
    "text=完成验证",
    "text=验证身份",
)
CHAT_TITLE = (
    '[class*="RightPanelHeader"] [class*="title"]',
    '[class*="ChatHeader"] [class*="title"]',
    '[class*="chatHeader"] [class*="title"]',
    '[class*="RightPanelHeader"] [class*="name"]',
)
MESSAGE_INPUTS = (
    '[data-contents="true"]',
    '.DraftEditor-root [contenteditable="true"]',
    '.DraftEditor-editor [contenteditable="true"]',
    '[contenteditable="true"][data-placeholder*="消息"]',
    '[contenteditable="true"][aria-label*="消息"]',
    '[contenteditable="true"]',
)
SEND_BUTTONS = (
    '[class*="publishBtn"]',
    '.e2e-send-msg-bt',
    'button[aria-label*="发送"]',
    '[role="button"][aria-label*="发送"]',
)
SEND_FAILED = (
    "text=发送失败",
    '[aria-label*="重试"]',
    '[class*="SendStatusretry"]',
)
STICKER_BUTTONS = (
    "svg.messageMsgInputiconAction",
    'button[aria-label*="表情"]',
    '[role="button"][aria-label*="表情"]',
    '[title*="表情"]',
)
STICKER_PANELS = (
    '[class*="emojiPanel"]',
    '[class*="EmojiPanel"]',
    '[class*="emoji_panel"]',
)
STICKER_ITEMS = (
    '[class*="emojiItem"]',
    '[class*="EmojiItem"]',
    '[class*="emoji_item"]',
    '[class*="stickerItem"]',
)
OUTGOING_BUBBLES = (
    '[class*="messageBoxisFromMe"]',
    '.messageMessageListlist [class*="isFromMe"]',
)
CONVERSATION_ROWS = (
    '[data-e2e="conversation-item"]',
    '[class*="conversationConversationItem"]',
    '[class*="ConversationItem"]',
)
MESSAGE_LISTS = (
    '[class*="MessageList"]',
    '[class*="messageList"]',
)


class DouyinError(RuntimeError):
    """抖音页面操作失败。"""


class LoginError(DouyinError):
    """Cookie 失效或未登录。"""


class RiskError(DouyinError):
    """出现安全验证。"""


class FriendNotFound(DouyinError):
    """找不到目标好友。"""


class SendError(DouyinError):
    """消息没有成功发出。"""


async def _first_visible(page: Page, selectors: tuple[str, ...], timeout_ms: int) -> Locator | None:
    per_selector = max(500, timeout_ms // max(1, len(selectors)))
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            await locator.wait_for(state="visible", timeout=per_selector)
            return locator
        except Exception:
            continue
    return None


async def _any_visible(page: Page, selectors: tuple[str, ...]) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() and await locator.is_visible():
                return True
        except Exception:
            continue
    return False


async def _safe_visible(locator: Locator) -> bool:
    try:
        return await locator.count() > 0 and await locator.is_visible()
    except Exception:
        return False


async def _text_matches(locator: Locator, expected: str) -> bool:
    try:
        return (await locator.inner_text(timeout=500)).strip() == expected.strip()
    except Exception:
        return False


class DouyinSession:
    """封装一个已注入 Cookie 的浏览器页面。"""

    def __init__(self, page: Page, timeout_seconds: float = 15) -> None:
        self.page = page
        self.timeout_ms = int(timeout_seconds * 1000)

    async def wait_ready(self) -> None:
        await self.page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=60_000)
        # 单页应用挂载需要时间，先给页面一个稳定的等待窗口
        for _ in range(20):
            if await _any_visible(self.page, LOGIN_REQUIRED) or await _any_visible(self.page, SEARCH_INPUTS):
                break
            await self.page.wait_for_timeout(500)

    async def ensure_logged_in(self) -> None:
        if await _any_visible(self.page, RISK_REQUIRED):
            raise RiskError("抖音要求安全验证，请在本机用浏览器手动通过验证后重新导出 Cookie")
        search = await _first_visible(self.page, SEARCH_INPUTS, 15_000)
        if search is not None:
            return
        if await _any_visible(self.page, LOGIN_REQUIRED):
            raise LoginError("Cookie 已失效：页面要求重新登录")
        raise LoginError("找不到私信搜索框，可能 Cookie 失效或页面结构已变化（可先运行 --diagnose）")

    async def open_friend(self, name: str, retries: int = 1) -> None:
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                await self._open_friend_once(name)
                return
            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    logger.warning("打开好友 %s 失败，%.0f 秒后重试：%s", name, 3, exc)
                    await self.page.wait_for_timeout(3_000)
        assert last_error is not None
        raise last_error

    async def _open_friend_once(self, name: str) -> None:
        search = await _first_visible(self.page, SEARCH_INPUTS, self.timeout_ms)
        if search is None:
            raise DouyinError("找不到私信搜索框")

        await search.click()
        await search.fill("")
        await search.fill(name)
        await self.page.wait_for_timeout(1_200)

        if await self._click_search_result(name):
            pass
        elif await self._click_conversation(name):
            pass
        else:
            raise FriendNotFound(f"私信列表和搜索结果里都找不到好友「{name}」")

        await self._confirm_chat(name)

    async def _click_search_result(self, name: str) -> bool:
        panel = self.page.locator('[class*="SearchPanel"]').first
        if not await _safe_visible(panel):
            return False

        nodes = panel.get_by_text(name, exact=True)
        for index in range(await nodes.count()):
            node = nodes.nth(index)
            if not await _safe_visible(node):
                continue
            # 从昵称节点逐层向上找那个带「发消息」按钮的结果行
            for depth in range(1, 6):
                row = node.locator(f"xpath=ancestor::*[{depth}]")
                button = row.locator('[class*="chat_btn"], [class*="chatBtn"]').first
                if await _safe_visible(button):
                    await button.click(force=True)
                    return True
            # 没有独立按钮时直接点这一行
            await node.click(force=True)
            return True
        return False

    async def _click_conversation(self, name: str) -> bool:
        for selector in CONVERSATION_ROWS:
            rows = self.page.locator(selector)
            for index in range(await rows.count()):
                row = rows.nth(index)
                if not await _safe_visible(row):
                    continue
                titles = row.locator(
                    '[class*="title"], [class*="Title"], [class*="name"], [class*="Name"]'
                )
                for title_index in range(await titles.count()):
                    if await _text_matches(titles.nth(title_index), name):
                        await row.click(force=True)
                        return True
        return False

    async def _confirm_chat(self, name: str) -> None:
        deadline = time.monotonic() + self.timeout_ms / 1000
        while time.monotonic() < deadline:
            for selector in CHAT_TITLE:
                titles = self.page.locator(selector)
                for index in range(min(await titles.count(), 5)):
                    title = titles.nth(index)
                    if await _safe_visible(title) and await _text_matches(title, name):
                        return
            await self.page.wait_for_timeout(500)

        # 标题类名改版时用输入框兜底，但必须确认聊天面板已经出现
        if await _first_visible(self.page, MESSAGE_INPUTS, 1_500) is None:
            raise DouyinError(f"点击好友「{name}」后没有打开聊天面板")
        logger.warning("未能确认聊天标题，但输入框已出现，继续执行（建议运行 --diagnose 校准）")

    async def message_input(self) -> Locator:
        editor = await _first_visible(self.page, MESSAGE_INPUTS, 10_000)
        if editor is None:
            raise DouyinError("找不到消息输入框")
        return editor

    async def send_text(self, text: str) -> None:
        editor = await self.message_input()
        await editor.click()
        await self.page.keyboard.insert_text(text)

        try:
            await self.page.wait_for_function(
                """([expected]) => {
                    const nodes = document.querySelectorAll(
                        '[contenteditable="true"], [data-contents="true"]'
                    );
                    return [...nodes].some(node => (node.innerText || '').includes(expected));
                }""",
                arg=[text],
                timeout=5_000,
            )
        except Exception as exc:
            raise SendError("文字没有写入聊天输入框") from exc

        await self.page.wait_for_timeout(random.randint(250, 700))
        await self._trigger_send()
        await self._confirm_sent(text)

    async def _trigger_send(self) -> None:
        for selector in SEND_BUTTONS:
            button = self.page.locator(selector).first
            if await _safe_visible(button):
                await button.click()
                return
        await self.page.keyboard.press("Enter")

    async def _confirm_sent(self, text: str) -> None:
        deadline = time.monotonic() + 15
        seen = False
        while time.monotonic() < deadline:
            if await _any_visible(self.page, SEND_FAILED):
                raise SendError("页面出现「发送失败」或重试标记")
            if not seen and await self._text_visible_in_chat(text):
                seen = True
                # 抖音会先渲染气泡再挂载状态图标，多观察一会儿避免误判成功
                await self.page.wait_for_timeout(1_500)
                if await _any_visible(self.page, SEND_FAILED):
                    raise SendError("消息发出后出现发送失败标记")
                return
            await self.page.wait_for_timeout(300)
        raise SendError("15 秒内没有在聊天记录里看到刚发送的消息")

    async def _text_visible_in_chat(self, text: str) -> bool:
        for selector in MESSAGE_LISTS:
            container = self.page.locator(selector).first
            if not await _safe_visible(container):
                continue
            nodes = container.get_by_text(text, exact=True)
            for index in range(await nodes.count()):
                if await _safe_visible(nodes.nth(index)):
                    return True
        # 结构变化时用整页匹配兜底；输入框在发送后会清空，误判概率较低
        nodes = self.page.get_by_text(text, exact=True)
        for index in range(await nodes.count()):
            if await _safe_visible(nodes.nth(index)):
                return True
        return False

    async def send_sticker(self, sticker: Sticker) -> None:
        panel = await self._open_sticker_panel()
        if sticker.category:
            await self._select_sticker_category(panel, sticker.category)

        item = await self._locate_sticker(panel, sticker)
        if item is None:
            raise SendError(
                f"表情面板里找不到「{sticker.label}」，请本地用 --show 校准 stickers 配置"
            )

        before = await self._outgoing_count()
        await item.click(force=True)
        await self.page.wait_for_timeout(500)
        if await self._composer_has_content():
            await self._trigger_send()
        await self._confirm_sticker_sent(before, sticker.label)

    async def _open_sticker_panel(self) -> Locator:
        button = await _first_visible(self.page, STICKER_BUTTONS, 5_000)
        if button is None:
            raise SendError("找不到表情按钮")
        await button.click()

        for selector in STICKER_PANELS:
            panel = self.page.locator(selector).first
            try:
                await panel.wait_for(state="visible", timeout=3_000)
                return panel
            except Exception:
                continue
        raise SendError("点击表情按钮后面板没有打开")

    async def _select_sticker_category(self, panel: Locator, category: str) -> None:
        tab = panel.get_by_text(category, exact=True).first
        if await _safe_visible(tab):
            await tab.click()
            await self.page.wait_for_timeout(600)

    async def _locate_sticker(self, panel: Locator, sticker: Sticker) -> Locator | None:
        # 优先按 name/title/alt 精确匹配，失败再用配置里的下标兜底
        title = panel.get_by_title(sticker.label, exact=True).first
        if await _safe_visible(title):
            return title
        alt = panel.get_by_alt_text(sticker.label, exact=True).first
        if await _safe_visible(alt):
            return alt

        if sticker.fallback_index is not None:
            for selector in STICKER_ITEMS:
                items = panel.locator(selector)
                if await items.count() > sticker.fallback_index:
                    return items.nth(sticker.fallback_index)

        for selector in STICKER_ITEMS:
            items = panel.locator(selector)
            if await items.count():
                return items.first
        return None

    async def _confirm_sticker_sent(self, before_count: int, label: str) -> None:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if await _any_visible(self.page, SEND_FAILED):
                raise SendError(f"发送表情「{label}」失败")

            after = await self._outgoing_count()
            if before_count >= 0 and after > before_count:
                await self.page.wait_for_timeout(1_200)
                if await _any_visible(self.page, SEND_FAILED):
                    raise SendError(f"发送表情「{label}」失败")
                return

            # 拿不到气泡数量时，用「输入框已清空」作为兜底信号
            if before_count < 0 and not await self._composer_has_content():
                await self.page.wait_for_timeout(1_500)
                if await _any_visible(self.page, SEND_FAILED):
                    raise SendError(f"发送表情「{label}」失败")
                return

            await self.page.wait_for_timeout(300)

        raise SendError(f"15 秒内未确认表情「{label}」已发出")

    async def _composer_has_content(self) -> bool:
        editor = await _first_visible(self.page, MESSAGE_INPUTS, 1_000)
        if editor is None:
            return False
        try:
            return bool((await editor.inner_text()).strip())
        except Exception:
            return False

    async def _outgoing_count(self) -> int:
        for selector in OUTGOING_BUBBLES:
            try:
                count = await self.page.locator(selector).count()
                if count:
                    return count
            except Exception:
                continue
        return -1

    async def diagnose(self) -> dict:
        """返回各关键选择器的命中情况，用于页面改版后的快速校准。"""
        checks = {
            "搜索框": SEARCH_INPUTS,
            "登录提示": LOGIN_REQUIRED,
            "安全验证": RISK_REQUIRED,
            "聊天标题": CHAT_TITLE,
            "消息输入框": MESSAGE_INPUTS,
            "发送按钮": SEND_BUTTONS,
            "表情按钮": STICKER_BUTTONS,
            "会话列表": CONVERSATION_ROWS,
        }
        report: dict[str, object] = {"url": self.page.url}
        for label, selectors in checks.items():
            hits = []
            for selector in selectors:
                try:
                    locator = self.page.locator(selector).first
                    if await locator.count() and await locator.is_visible():
                        hits.append(selector)
                except Exception:
                    continue
            report[label] = hits
        return report
