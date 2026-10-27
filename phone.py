"""ADB 设备层：把 adb 命令封装成方法，供插件调用。

只用标准库；OCR 依赖 Windows 自带的 Windows.Media.Ocr（非 Windows 平台会明确返回不支持）。
"""
from __future__ import annotations

import base64
import re
import struct
import shutil
import subprocess
import time
from pathlib import Path


class AdbError(RuntimeError):
    """adb 调用失败。"""


# 常用应用的别名表：说「微信」就能开，不用记包名。
# 欢迎在 PR 里补充更多包名。
APP_ALIASES = {
    "微信": "com.tencent.mm",
    "wechat": "com.tencent.mm",
    "qq": "com.tencent.mobileqq",
    "qq空间": "com.qzone",
    "支付宝": "com.eg.android.AlipayGphone",
    "alipay": "com.eg.android.AlipayGphone",
    "淘宝": "com.taobao.taobao",
    "taobao": "com.taobao.taobao",
    "抖音": "com.ss.android.ugc.aweme",
    "tiktok": "com.ss.android.ugc.aweme",
    "快手": "com.smile.gifmaker",
    "b站": "tv.danmaku.bili",
    "哔哩哔哩": "tv.danmaku.bili",
    "bilibili": "tv.danmaku.bili",
    "小红书": "com.xingin.xhs",
    "微博": "com.sina.weibo",
    "知乎": "com.zhihu.android",
    "高德": "com.autonavi.minimap",
    "amap": "com.autonavi.minimap",
    "网易云": "com.netease.cloudmusic",
    "网易云音乐": "com.netease.cloudmusic",
    "qq音乐": "com.tencent.qqmusic",
    "设置": "com.android.settings",
    "settings": "com.android.settings",
    "相机": "com.android.camera",
    "camera": "com.android.camera",
    "相册": "com.android.gallery3d",
    "gallery": "com.android.gallery3d",
    "电话": "com.android.dialer",
    "dialer": "com.android.dialer",
    "短信": "com.android.mms",
    "sms": "com.android.mms",
    "浏览器": "com.android.browser",
    "browser": "com.android.browser",
    "文件管理": "com.android.documentsui",
    "files": "com.android.documentsui",
    "时钟": "com.android.deskclock",
    "clock": "com.android.deskclock",
    "计算器": "com.android.calculator2",
    "calculator": "com.android.calculator2",
    "应用商店": "com.android.vending",
    "play": "com.android.vending",
}

CJK_SPACE = re.compile(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])")


class PhoneDevice:
    """一台通过 adb 连接的安卓设备。"""

    def __init__(
        self,
        adb_path: str = "adb",
        serial: str | None = None,
        shots_dir: str | Path = "",
        timeout: int = 30,
    ) -> None:
        self.adb_path = self._resolve_adb(adb_path)
        self.serial = (serial or "").strip() or None
        self.shots_dir = Path(shots_dir or Path.cwd() / "phone_shots")
        self.shots_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout

    # ---------- 基础 ----------

    @staticmethod
    def _resolve_adb(adb_path: str) -> str:
        p = (adb_path or "adb").strip()
        if Path(p).is_file():
            return p
        found = shutil.which(p) or shutil.which("adb")
        if found:
            return found
        return p  # 交给运行时去报错，错误信息更清楚

    def _run(self, *args: str, timeout: int | None = None) -> tuple[int, str, str]:
        cmd = [self.adb_path]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += list(args)
        try:
            p = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout or self.timeout,
            )
        except FileNotFoundError as e:
            raise AdbError(f"找不到 adb：{self.adb_path}（请在插件配置里填绝对路径）") from e
        except subprocess.TimeoutExpired:
            raise AdbError(f"adb 命令超时：{' '.join(args)}") from None
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()

    def devices(self) -> str:
        rc, out, err = self._run("devices", "-l")
        if rc != 0:
            raise AdbError(err or out or "adb devices 失败")
        return out

    def ensure_online(self) -> None:
        rc, out, _ = self._run("devices")
        lines = [l for l in out.splitlines()[1:] if l.strip()]
        if not lines:
            raise AdbError("没有设备在线：USB 插上并允许 USB 调试，或先 adb connect <ip:port>")
        if all("offline" in l or "unauthorized" in l for l in lines):
            raise AdbError("设备未授权：看手机屏幕上的「允许 USB 调试」弹窗")

    def screen_size(self) -> tuple[int, int]:
        rc, out, err = self._run("shell", "wm", "size")
        m = re.search(r"(\d+)x(\d+)", out or "")
        if not m:
            raise AdbError(f"读不到屏幕分辨率：{out or err}")
        return int(m.group(1)), int(m.group(2))

    # ---------- 动作 ----------

    def tap(self, x: int, y: int) -> str:
        rc, out, err = self._run("shell", "input", "tap", str(int(x)), str(int(y)))
        return "ok" if rc == 0 else (err or out)

    def longpress(self, x: int, y: int, ms: int = 800) -> str:
        rc, out, err = self._run(
            "shell", "input", "swipe", str(int(x)), str(int(y)),
            str(int(x)), str(int(y)), str(int(ms)),
        )
        return "ok" if rc == 0 else (err or out)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> str:
        rc, out, err = self._run(
            "shell", "input", "swipe", str(int(x1)), str(int(y1)),
            str(int(x2)), str(int(y2)), str(int(ms)),
        )
        return "ok" if rc == 0 else (err or out)

    def key(self, name: str) -> str:
        rc, out, err = self._run("shell", "input", "keyevent", name.upper())
        return "ok" if rc == 0 else (err or out)

    def wake(self) -> str:
        return self.key("KEYCODE_WAKEUP")

    def anim(self, on: bool) -> str:
        value = "0" if not on else "1"
        for k in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale"):
            self._run("shell", "settings", "put", "global", k, value)
        return "动画已" + ("关闭" if not on else "开启")

    # ---------- 界面读取 ----------

    def dump_ui_xml(self, retries: int = 2) -> str:
        xml = ""
        for _ in range(retries + 1):
            self._run("shell", "uiautomator", "dump", "/sdcard/window_dump.xml", timeout=60)
            rc, out, err = self._run("exec-out", "cat", "/sdcard/window_dump.xml", timeout=60)
            if out and "<hierarchy" in out:
                return out
            xml = out or err
            time.sleep(0.4)
        return xml

    @staticmethod
    def parse_nodes(xml: str) -> list[dict]:
        nodes = []
        for tag in re.findall(r"<node[^>]*>", xml):
            def attr(name: str) -> str:
                m = re.search(r'%s="([^"]*)"' % name, tag)
                return m.group(1) if m else ""

            bounds = attr("bounds")
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if not m:
                continue
            x1, y1, x2, y2 = map(int, m.groups())
            label = attr("text") or attr("content-desc")
            rid = attr("resource-id")
            if not label and not rid:
                continue
            nodes.append({
                "label": label,
                "id": rid,
                "clickable": attr("clickable") == "true",
                "cx": (x1 + x2) // 2,
                "cy": (y1 + y2) // 2,
                "bounds": bounds,
            })
        return nodes

    def ui(self, limit: int = 120) -> str:
        xml = self.dump_ui_xml()
        if "<hierarchy" not in xml:
            return "读不到界面控件树"
        nodes = self.parse_nodes(xml)
        if not nodes:
            return "这个界面没有可读的控件"
        lines = []
        for i, n in enumerate(nodes[:limit], 1):
            label = (n["label"] or "")[:24]
            rid = n["id"].split("/")[-1][:26] if n["id"] else ""
            flag = "*" if n["clickable"] else " "
            lines.append("%3d %s %-24s id=%-26s (%d,%d)" % (i, flag, label, rid, n["cx"], n["cy"]))
        return "\n".join(lines)

    def focus(self) -> str:
        rc, out, err = self._run("shell", "dumpsys window", timeout=60)
        m = re.search(r"mCurrentFocus=Window\{[^}]*?\s([\w.]+/[\w.$]+)\}", out)
        if not m:
            rc2, out2, _ = self._run("shell", "dumpsys activity", "activities", timeout=60)
            m = re.search(r"mResumedActivity:.*?([\w.]+/[\w.$]+)", out2)
        if not m:
            return err or "读不到前台应用"
        full = m.group(1)
        return f"{full}\n包名：{full.split('/')[0]}"

    def tap_text(self, text: str) -> str:
        nodes = self.parse_nodes(self.dump_ui_xml())
        hit = next((n for n in nodes if n["label"] and text in n["label"]), None)
        if not hit:
            hit = next((n for n in nodes if n["label"] and n["label"] in text), None)
        if not hit:
            return f"没找到文字：{text}"
        self.tap(hit["cx"], hit["cy"])
        return f"已点「{hit['label'][:20]}」({hit['cx']},{hit['cy']})"

    def tap_id(self, id_part: str) -> str:
        nodes = self.parse_nodes(self.dump_ui_xml())
        hit = next((n for n in nodes if n["id"] and id_part in n["id"]), None)
        if not hit:
            return f"没找到 id 含「{id_part}」的控件"
        self.tap(hit["cx"], hit["cy"])
        return f"已点 id={hit['id']} ({hit['cx']},{hit['cy']})"

    # ---------- 截图 ----------

    def shot(self) -> Path:
        path = self.shots_dir / (time.strftime("%Y%m%d-%H%M%S") + ".png")
        with open(path, "wb") as f:
            p = subprocess.run(
                [self.adb_path] + (["-s", self.serial] if self.serial else []) + ["exec-out", "screencap", "-p"],
                stdout=f, stderr=subprocess.PIPE, timeout=60,
            )
        if p.returncode != 0:
            raise AdbError((p.stderr or b"").decode("utf-8", "replace")[:200] or "截屏失败")
        return path

    def shot_small(self, max_width: int = 900, quality: int = 82) -> Path:
        """截图并缩放成 JPEG（可选依赖 Pillow；没装就返回原图）。"""
        raw = self.shot()
        try:
            from PIL import Image
        except ImportError:
            return raw
        try:
            im = Image.open(raw).convert("RGB")
            w, h = im.size
            if w > max_width:
                im = im.resize((max_width, int(h * max_width / w)), Image.LANCZOS)
            out = raw.with_suffix(".jpg")
            im.save(out, "JPEG", quality=quality, optimize=True)
            raw.unlink(missing_ok=True)
            return out
        except Exception:
            return raw

    # ---------- 输入 ----------

    def type_text(self, text: str) -> str:
        """直接往当前焦点输入文字（中文需要 ADBKeyboard 且已聚焦）。"""
        if any(ord(c) > 127 for c in text):
            b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
            rc, out, err = self._run("shell", "am", "broadcast", "-a", "ADB_INPUT_B64", "--es", "msg", b64)
            if rc != 0 or "Broadcast completed" not in (out + err):
                return "中文输入失败：需要安装 ADBKeyboard 并设为当前输入法"
            return "ok"
        rc, out, err = self._run("shell", "input", "text", text.replace(" ", "%s"))
        return "ok" if rc == 0 else (err or out)

    def ime_available(self, ime_id: str) -> bool:
        rc, out, _ = self._run("shell", "ime", "list", "-s")
        return ime_id in out

    def current_ime(self) -> str:
        return self._run("shell", "settings", "get", "secure", "default_input_method")[1]

    def set_ime(self, ime_id: str) -> str:
        self._run("shell", "ime", "set", ime_id)
        time.sleep(0.6)
        now = self.current_ime()
        return "ok" if ime_id in now else f"切换输入法失败：当前是 {now}"

    def ime_shown(self) -> bool:
        rc, out, _ = self._run("shell", "dumpsys", "input_method", timeout=30)
        return "mInputShown=true" in out or "mIsInputViewShown=true" in out

    def _screencap_raw(self) -> tuple[int, int, bytes]:
        """原始截屏（RGBA + 12 字节头），不需要 Pillow。"""
        cmd = [self.adb_path] + (["-s", self.serial] if self.serial else []) + ["exec-out", "screencap"]
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=60)
        except FileNotFoundError as e:
            raise AdbError(f"找不到 adb：{self.adb_path}") from e
        if p.returncode != 0:
            raise AdbError((p.stderr or b"").decode("utf-8", "replace")[:200] or "截屏失败")
        data = p.stdout or b""
        if len(data) < 16:
            raise AdbError("截屏返回为空")
        w, h, _fmt = struct.unpack("<III", data[:12])
        return w, h, data[12:]

    def input_bar_candidates(self, top_ratio: float = 0.84) -> list[tuple[int, int]]:
        """在屏幕底部找「输入条」候选：接近纯白的横向长条，按位置从下到上。

        做法：原始截屏（不需要 Pillow）→ 逐行取中间区域的亮度 → 找连续高亮带。
        跨机型比按比例猜稳；候选会依次尝试，点不中换下一个。
        """
        try:
            w, h, pixels = self._screencap_raw()
        except AdbError:
            return None
        if w <= 0 or h <= 0 or len(pixels) < w * h * 4:
            return None

        def luma(x: int, y: int) -> int:
            i = (y * w + x) * 4
            r, g, b = pixels[i], pixels[i + 1], pixels[i + 2]
            return (r * 299 + g * 587 + b * 114) // 1000

        y_start = int(h * top_ratio)
        step_y = max(2, h // 400)
        xs = list(range(int(w * 0.20), int(w * 0.80), max(2, w // 120)))

        bands: list[tuple[int, int]] = []
        begin = None
        last = y_start
        for y in range(y_start, h, step_y):
            mean = sum(luma(x, y) for x in xs) / len(xs)
            bright = mean >= 244          # 输入条接近纯白；聊天背景通常 230~240
            if bright and begin is None:
                begin = y
            elif not bright and begin is not None:
                if 18 <= y - begin <= 260:
                    bands.append((begin, y))
                begin = None
            last = y
        if begin is not None and 18 <= last - begin <= 260:
            bands.append((begin, last))
        return [(int(w * 0.35), (s + e) // 2) for s, e in bands]

    def detect_input_bar(self, top_ratio: float = 0.84) -> tuple[int, int] | None:
        """只要一个最佳猜测（最靠下的高亮条）；找不到返回 None。"""
        cands = self.input_bar_candidates(top_ratio)
        return cands[-1] if cands else None

    def focus_input(self, tries: tuple[float, ...] = (0.93, 0.945, 0.915, 0.96, 0.88)) -> str:
        """点中输入框：先在截图上找输入条，找不到再按比例试；键盘弹出即成功。"""
        w, h = self.screen_size()
        x = int(w * 0.32)
        detected = self.input_bar_candidates()
        # 优先"像输入框"的位置：靠近屏幕高度 93% 的排前面；
        # 太靠底的先不用（那多半是手势条，点下去可能触发返回）
        primary = [c for c in detected if c[1] < h * 0.965]
        secondary = [c for c in detected if c[1] >= h * 0.965]
        primary.sort(key=lambda c: abs(c[1] - h * 0.93))
        candidates = [(cx, cy, "截图定位") for cx, cy in primary[:3]]
        candidates += [(x, int(h * r), "比例试探") for r in tries]
        candidates += [(cx, cy, "截图定位") for cx, cy in secondary[:2]]

        for cx, cy, how in candidates:
            self.tap(cx, cy)
            time.sleep(0.7)
            if self.ime_shown():
                return f"输入框已点中 ({cx},{cy})（{how}）"
        return "没点中输入框，可以先用 phone_look 看一眼界面再手填坐标"

    def type_into_input(self, text: str, ime_id: str = "com.android.adbkeyboard/.AdbIME") -> str:
        """点中输入框再输入（微信一类读不到控件的聊天框用这个）。"""
        if any(ord(c) > 127 for c in text) and self.ime_available(ime_id):
            if ime_id not in self.current_ime():
                self.set_ime(ime_id)
        got = self.focus_input()
        if "没点中" in got:
            return got
        return self.type_text(text)

    # ---------- 应用 ----------

    def installed_packages(self) -> list[str]:
        rc, out, err = self._run("shell", "pm", "list", "packages", timeout=60)
        if rc != 0:
            raise AdbError(err or out)
        return [l.split(":", 1)[1] for l in out.splitlines() if l.startswith("package:")]

    def resolve_app(self, name: str) -> tuple[str | None, str]:
        key = name.strip()
        for prefix in ("打开", "启动", "运行", "open "):
            if key.lower().startswith(prefix):
                key = key[len(prefix):].strip()
        for alias, pkg in APP_ALIASES.items():
            if alias.lower() == key.lower():
                return pkg, "别名"
        pkgs = self.installed_packages()
        if key in pkgs:
            return key, "包名"
        hits = [p for p in pkgs if key.lower() in p.lower()]
        if len(hits) == 1:
            return hits[0], "模糊匹配"
        if len(hits) > 1:
            return None, "有多个候选：" + ", ".join(hits[:8])
        return None, "没找到对应应用"

    def open_app(self, name: str) -> str:
        pkg, why = self.resolve_app(name)
        if not pkg:
            return why
        rc, out, err = self._run(
            "shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"
        )
        return f"已打开 {pkg}（{why}）" if rc == 0 else (err or out)

    # ---------- OCR（仅 Windows） ----------

    @staticmethod
    def ocr_supported() -> bool:
        return shutil.which("powershell") is not None

    def ocr(self, image: Path | None = None, script: str | None = None) -> str:
        """对截图做 OCR，返回「(x,y) 文字」行。依赖 ocr_win.ps1（Windows）。"""
        img = image or self.shot()
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if not ps:
            return "当前系统没有 PowerShell，OCR 只在 Windows 上可用"
        script_path = script or str(Path(__file__).with_name("ocr_win.ps1"))
        p = subprocess.run(
            [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path, "-Path", str(img)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
        )
        text = (p.stdout or "").strip()
        text = CJK_SPACE.sub("", text)
        if not text:
            text = "(没识别到文字)" + ((("：" + p.stderr[:160]) if p.stderr else ""))
        return text
