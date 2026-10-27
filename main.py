"""AstrBot 插件：让机器人通过 adb 操作一台安卓手机。

设计要点：
  - 读界面优先走控件树（uiautomator），读不到时自动退到 OCR（Windows）；
  - 点按钮优先按文字 / resource-id，最后才用坐标；
  - 遇到支付、密码一类的敏感界面会先停下，等主人确认；
  - 所有路径与白名单都在插件配置里，不写死任何本机路径。
"""
from __future__ import annotations

import time

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star, StarTools, register

from .phone import AdbError, PhoneDevice

DEFAULT_SENSITIVE = [
    "支付", "密码", "银行", "转账", "验证码", "钱包", "收款", "付款", "免密",
    "身份证", "余额", "充值", "提现", "确认支付", "输入密码", "指纹", "面容",
]


@register(
    "astrbot_plugin_adb_phone",
    "dsh",
    "用 adb 操作安卓手机：读界面、点按、打字、开应用。微信等读不到控件的界面自动走 OCR。",
    "0.1.0",
)
class AdbPhonePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        self._allowed_until = 0.0

        shots = self.config.get("shots_dir") or str(StarTools.get_data_dir("adb_phone") / "shots")
        self.device = PhoneDevice(
            adb_path=self.config.get("adb_path") or "adb",
            serial=self.config.get("device_serial") or None,
            shots_dir=shots,
            timeout=int(self.config.get("command_timeout") or 30),
        )
        self.ime_auto = self.config.get("adb_keyboard_ime") or "com.android.adbkeyboard/.AdbIME"
        self.ime_human = self.config.get("human_ime") or ""

    # ---------- 权限 ----------

    def _senders(self) -> set[str]:
        return {str(x).strip() for x in (self.config.get("allowed_senders") or []) if str(x).strip()}

    def _platforms(self) -> set[str]:
        return {str(x).strip() for x in (self.config.get("allowed_platforms") or []) if str(x).strip()}

    def _ok(self, event: AstrMessageEvent) -> str:
        """返回空串表示有权限，否则返回拒绝原因。"""
        senders = self._senders()
        if not senders:
            return "插件还没配置 allowed_senders（允许操作手机的账号），先到配置里填。"
        try:
            sid = str(event.get_sender_id())
            pid = str(event.get_platform_id())
        except Exception:
            return "读不到消息来源，拒绝操作。"
        if sid not in senders:
            return "（没有权限操作手机）"
        platforms = self._platforms()
        if platforms and pid not in platforms:
            return "（这个平台没有操作手机的权限）"
        return ""

    # ---------- 敏感界面闸门 ----------

    def _keywords(self) -> list[str]:
        return list(self.config.get("sensitive_keywords") or DEFAULT_SENSITIVE)

    def _gate_open(self) -> bool:
        return time.time() < self._allowed_until

    async def _sensitive_hit(self) -> str:
        try:
            xml = self.device.dump_ui_xml()
            nodes = self.device.parse_nodes(xml)
            blob = " ".join(n["label"] for n in nodes)
        except Exception:
            return ""
        for k in self._keywords():
            if k and k in blob:
                return k
        return ""

    async def _guard(self, event: AstrMessageEvent, *, need_confirm: bool) -> str:
        deny = self._ok(event)
        if deny:
            return deny
        if need_confirm:
            hit = await self._sensitive_hit()
            if hit and not self._gate_open():
                return (
                    f"⚠️ 当前界面出现了「{hit}」，涉及钱或账号安全，我先停下。"
                    "需要主人明确说「确认可以」，我再动手。"
                )
        return ""

    # ---------- 工具 ----------

    @filter.llm_tool(name="phone_confirm")
    async def phone_confirm(self, event: AstrMessageEvent):
        """主人明确说「确认可以操作」之后调用，解锁敏感界面 3 分钟。"""
        deny = self._ok(event)
        if deny:
            yield deny
            return
        seconds = int(self.config.get("confirm_seconds") or 180)
        self._allowed_until = time.time() + seconds
        yield f"已解锁 {seconds // 60} 分钟，这期间可以操作敏感界面。"

    @filter.llm_tool(name="phone_devices")
    async def phone_devices(self, event: AstrMessageEvent):
        """看当前连了哪些安卓设备（排查连不上时用）。"""
        deny = self._ok(event)
        if deny:
            yield deny
            return
        try:
            yield self.device.devices()
        except AdbError as e:
            yield f"adb 出错：{e}"

    @filter.llm_tool(name="phone_focus")
    async def phone_focus(self, event: AstrMessageEvent):
        """看手机现在前台是哪个应用，确认自己走到哪一步了。"""
        deny = await self._guard(event, need_confirm=False)
        if deny:
            yield deny
            return
        try:
            yield self.device.focus()
        except AdbError as e:
            yield f"出错：{e}"

    @filter.llm_tool(name="phone_ui")
    async def phone_ui(self, event: AstrMessageEvent):
        """读当前界面控件树（不发截图，快）。每行：编号 *? 文字 id=资源id (x,y)，带 * 可点。
        常规操作优先用它；读不到文字时自动改用 OCR。"""
        deny = await self._guard(event, need_confirm=False)
        if deny:
            yield deny
            return
        try:
            ui = self.device.ui(int(self.config.get("max_ui_nodes") or 120))
        except AdbError as e:
            yield f"出错：{e}"
            return
        if "读不到" in ui or "没有可读" in ui:
            yield "控件树读不到文字，改用 OCR："
            try:
                yield self.device.ocr()
            except Exception as e:
                yield f"OCR 也失败了：{e}"
            return
        yield ui

    @filter.llm_tool(name="phone_ocr")
    async def phone_ocr(self, event: AstrMessageEvent):
        """对当前屏幕做 OCR，返回「(x,y) 文字」。微信等屏蔽控件树的应用用这个。"""
        deny = await self._guard(event, need_confirm=False)
        if deny:
            yield deny
            return
        try:
            yield self.device.ocr()
        except Exception as e:
            yield f"OCR 失败：{e}"

    @filter.llm_tool(name="phone_look")
    async def phone_look(self, event: AstrMessageEvent):
        """看一眼屏幕：把截图发给主人，同时列出界面上的控件。只在需要看图片/颜色时用。"""
        deny = await self._guard(event, need_confirm=False)
        if deny:
            yield deny
            return
        try:
            path = self.device.shot_small()
        except AdbError as e:
            yield f"截屏失败：{e}"
            return
        try:
            yield event.chain_result([Image.fromFileSystem(str(path))])
        except Exception as e:
            logger.warning(f"[adb_phone] 发图失败：{e!r}")
        try:
            yield "截图已发出。界面控件：\n" + self.device.ui(int(self.config.get("max_ui_nodes") or 120))
        except Exception:
            yield "截图已发出。"

    @filter.llm_tool(name="phone_tap")
    async def phone_tap(self, event: AstrMessageEvent, x: int, y: int):
        """点屏幕坐标。

        Args:
            x(number): 横坐标
            y(number): 纵坐标
        """
        deny = await self._guard(event, need_confirm=True)
        if deny:
            yield deny
            return
        try:
            yield self.device.tap(x, y)
        except AdbError as e:
            yield f"出错：{e}"

    @filter.llm_tool(name="phone_tap_text")
    async def phone_tap_text(self, event: AstrMessageEvent, text: str):
        """按界面文字点（不用坐标）。

        Args:
            text(string): 控件上的文字或描述，可以是一段
        """
        deny = await self._guard(event, need_confirm=True)
        if deny:
            yield deny
            return
        try:
            yield self.device.tap_text(text)
        except AdbError as e:
            yield f"出错：{e}"

    @filter.llm_tool(name="phone_tap_id")
    async def phone_tap_id(self, event: AstrMessageEvent, id_part: str):
        """按 resource-id 片段点（最稳，如 send、search）。

        Args:
            id_part(string): resource-id 里的一段
        """
        deny = await self._guard(event, need_confirm=True)
        if deny:
            yield deny
            return
        try:
            yield self.device.tap_id(id_part)
        except AdbError as e:
            yield f"出错：{e}"

    @filter.llm_tool(name="phone_tap_ocr")
    async def phone_tap_ocr(self, event: AstrMessageEvent, text: str):
        """按 OCR 认出来的文字点（微信等读不到控件树时用）。

        Args:
            text(string): 屏幕上的文字，可以是一段
        """
        deny = await self._guard(event, need_confirm=True)
        if deny:
            yield deny
            return
        try:
            import re as _re

            text_out = self.device.ocr()
            rows = []
            for line in text_out.splitlines():
                m = _re.match(r"\((\d+),(\d+)\)\s+(.*)", line)
                if m:
                    rows.append((int(m.group(1)), int(m.group(2)), m.group(3)))
            want = text.replace(" ", "")
            hit = next((r for r in rows if want and want in r[2].replace(" ", "")), None)
            if not hit:
                hit = next((r for r in rows if want and r[2].replace(" ", "") in want), None)
            if not hit:
                sample = "；".join(r[2] for r in rows[:8])
                yield f"没在屏幕上找到「{text}」。现在能看到：{sample or '（空）'}"
                return
            yield self.device.tap(hit[0], hit[1]) + f"  ← 点的「{hit[2]}」"
        except AdbError as e:
            yield f"出错：{e}"

    @filter.llm_tool(name="phone_tap_input")
    async def phone_tap_input(self, event: AstrMessageEvent):
        """点中输入框（微信聊天底部那种读不到控件的输入框）。会确认键盘真的弹出。"""
        deny = await self._guard(event, need_confirm=True)
        if deny:
            yield deny
            return
        try:
            yield self.device.focus_input()
        except AdbError as e:
            yield f"出错：{e}"

    @filter.llm_tool(name="phone_type_input")
    async def phone_type_input(self, event: AstrMessageEvent, text: str):
        """点中输入框并输入文字（聊天首选：会先切输入法、点框、再打字）。

        Args:
            text(string): 要输入的内容，中文也可以
        """
        deny = await self._guard(event, need_confirm=True)
        if deny:
            yield deny
            return
        try:
            result = self.device.type_into_input(text, self.ime_auto)
        except AdbError as e:
            yield f"出错：{e}"
            return
        yield f"已输入：{text}" if result == "ok" else result

    @filter.llm_tool(name="phone_text")
    async def phone_text(self, event: AstrMessageEvent, text: str):
        """往当前焦点输入文字（先点好输入框再用）。

        Args:
            text(string): 要输入的内容
        """
        deny = await self._guard(event, need_confirm=True)
        if deny:
            yield deny
            return
        try:
            yield self.device.type_text(text)
        except AdbError as e:
            yield f"出错：{e}"

    @filter.llm_tool(name="phone_key")
    async def phone_key(self, event: AstrMessageEvent, key: str):
        """按系统键。

        Args:
            key(string): BACK / HOME / ENTER / WAKEUP / VOLUME_UP / VOLUME_DOWN / POWER
        """
        deny = await self._guard(event, need_confirm=False)
        if deny:
            yield deny
            return
        allowed = {"BACK", "HOME", "ENTER", "WAKEUP", "VOLUME_UP", "VOLUME_DOWN", "POWER"}
        k = str(key).strip().upper()
        if k not in allowed:
            yield "只支持：" + " / ".join(sorted(allowed))
            return
        try:
            yield self.device.key(k)
        except AdbError as e:
            yield f"出错：{e}"

    @filter.llm_tool(name="phone_swipe")
    async def phone_swipe(self, event: AstrMessageEvent, x1: int, y1: int, x2: int, y2: int, ms: int = 300):
        """滑动屏幕。

        Args:
            x1(number): 起点 x
            y1(number): 起点 y
            x2(number): 终点 x
            y2(number): 终点 y
            ms(number): 用时毫秒
        """
        deny = await self._guard(event, need_confirm=True)
        if deny:
            yield deny
            return
        try:
            yield self.device.swipe(x1, y1, x2, y2, ms)
        except AdbError as e:
            yield f"出错：{e}"

    @filter.llm_tool(name="phone_open")
    async def phone_open(self, event: AstrMessageEvent, app: str):
        """打开一个应用，说名字就行（微信 / QQ / b站 / 设置），也接受包名。

        Args:
            app(string): 应用名或包名
        """
        deny = await self._guard(event, need_confirm=True)
        if deny:
            yield deny
            return
        try:
            yield self.device.open_app(app)
        except AdbError as e:
            yield f"出错：{e}"

    @filter.llm_tool(name="phone_apps")
    async def phone_apps(self, event: AstrMessageEvent, keyword: str = ""):
        """列出手机上装的应用（可按关键词过滤），用来找包名。

        Args:
            keyword(string): 过滤词
        """
        deny = await self._guard(event, need_confirm=False)
        if deny:
            yield deny
            return
        try:
            pkgs = self.device.installed_packages()
        except AdbError as e:
            yield f"出错：{e}"
            return
        kw = keyword.strip().lower()
        hits = [p for p in pkgs if kw in p.lower()] if kw else pkgs
        yield "\n".join(hits[:120]) or "没找到"

    @filter.llm_tool(name="phone_anim")
    async def phone_anim(self, event: AstrMessageEvent, mode: str):
        """开关系统动画。关掉以后每步操作快 0.3~1 秒。

        Args:
            mode(string): off 或 on
        """
        deny = await self._guard(event, need_confirm=False)
        if deny:
            yield deny
            return
        m = str(mode).strip().lower()
        if m not in {"off", "on"}:
            yield "mode 只能是 off 或 on"
            return
        try:
            yield self.device.anim(m == "on")
        except AdbError as e:
            yield f"出错：{e}"

    @filter.llm_tool(name="phone_ime")
    async def phone_ime(self, event: AstrMessageEvent, mode: str):
        """切换输入法：auto=机器人打字用（ADBKeyboard），human=换回主人自己的键盘。

        Args:
            mode(string): auto 或 human
        """
        deny = await self._guard(event, need_confirm=False)
        if deny:
            yield deny
            return
        m = str(mode).strip().lower()
        target = self.ime_auto if m == "auto" else self.ime_human
        if not target:
            yield "没有配置 human_ime（主人自己的输入法 id），先到插件配置里填。"
            return
        try:
            yield self.device.set_ime(target)
        except AdbError as e:
            yield f"出错：{e}"

    @filter.command("手机状态", alias={"phone_status"})
    async def phone_status_command(self, event: AstrMessageEvent):
        """命令行查看连接状态。"""
        deny = self._ok(event)
        if deny:
            yield event.plain_result(deny)
            return
        try:
            yield event.plain_result(self.device.devices())
        except AdbError as e:
            yield event.plain_result(f"adb 出错：{e}")
