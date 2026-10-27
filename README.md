# astrbot_plugin_adb_phone

让 AstrBot 里的机器人通过 **adb 直接操作一台安卓手机**：读界面、点按钮、输入文字、打开应用。

不是靠“看截图猜位置”，而是**优先读控件树**（uiautomator），读不到时才退到 **OCR**（Windows 自带引擎）——
所以像微信这种屏蔽了无障碍信息的应用，也能读、能点、能打字。

> An AstrBot plugin that lets your bot drive an Android phone over adb:
> it reads the UI tree first and falls back to Windows' built-in OCR,
> so even apps that block accessibility (e.g. WeChat) remain operable.

---

## 能力

| 工具 | 作用 |
|---|---|
| `phone_ui` | 读当前界面控件树：文字 / resource-id / 坐标 / 是否可点（不发截图，快） |
| `phone_ocr` | 对当前屏幕做 OCR，返回「(x,y) 文字」——控件树读不到时用 |
| `phone_focus` | 当前前台是哪个应用 |
| `phone_look` | 截图发给主人，并附上控件列表（只在需要看图片、颜色时用） |
| `phone_tap` | 按坐标点 |
| `phone_tap_text` | 按界面文字点（不用坐标） |
| `phone_tap_id` | 按 resource-id 片断点（最稳） |
| `phone_tap_ocr` | 按 OCR 认出来的文字点 |
| `phone_tap_input` | 点中输入框，并确认键盘真的弹出来 |
| `phone_type_input` | 点中输入框 → 切输入法 → 打字（聊天首选，中文可用） |
| `phone_text` | 往当前焦点输入文字 |
| `phone_key` | BACK / HOME / ENTER / WAKEUP / POWER / 音量 |
| `phone_swipe` | 滑动 |
| `phone_open` | 打开应用，说名字即可（微信 / QQ / b站 / 设置），也接受包名（内置 30+ 别名） |
| `phone_apps` | 列出已安装应用 |
| `phone_anim` | 关掉系统动画，每步快 0.3~1 秒 |
| `phone_ime` | 切换输入法（机器人打字 / 主人自己打） |
| `phone_confirm` | 解锁敏感界面 3 分钟 |
| `phone_devices` | 查看连接的设备（排查用） |

命令：`/手机状态`（别名 `phone_status`）查看连接状态。

---

## 安装

1. 把本目录放进 AstrBot 的 `data/plugins/` 下（目录名 `astrbot_plugin_adb_phone`）。
2. 装依赖（可选，只有缩放截图需要）：
   ```bash
   pip install pillow
   ```
3. 重启 AstrBot，在面板里打开插件配置，**至少填 `allowed_senders`**（你的 QQ 号），否则任何人都用不了。

### 手机侧准备

```bash
adb devices                  # 确认识别到设备
adb shell settings put global window_animation_scale 0   # 可选：关动画提速
```

- 手机打开「开发者选项 → USB 调试」，插线后允许调试。
- 想输入**中文**，需要装 [ADBKeyboard](https://github.com/senzhk/ADBKeyBoard) 并把它的 IME id 填进 `adb_keyboard_ime`。
- 无线调试也可以：先 `adb connect <ip>:5555`，再把设备序列号填进 `device_serial`。

---

## 配置说明

| 键 | 说明 |
|---|---|
| `allowed_senders` | **必填**。允许操作手机的账号 ID；留空 = 谁都用不了 |
| `allowed_platforms` | 可选。限定平台，留空表示不限 |
| `adb_path` | adb 路径，默认从 PATH 找 |
| `device_serial` | 多设备时指定序列号 |
| `shots_dir` | 截图目录，留空用插件数据目录 |
| `max_ui_nodes` | `phone_ui` 返回条数上限 |
| `adb_keyboard_ime` / `human_ime` | 两个输入法的 IME id |
| `sensitive_keywords` | 屏幕上出现这些词就先停下（支付、密码、转账…） |
| `confirm_seconds` | `phone_confirm` 解锁时长 |

---

## 安全设计

- **默认不可用**：`allowed_senders` 为空时所有工具直接拒绝——避免装完就被群里任何人拿来控手机。
- **敏感界面闸门**：点按/输入前会先读界面，出现“支付 / 密码 / 转账 / 验证码”等词时停下，等人说「确认可以」再放行。
- **不写死任何本机路径**：adb 路径、截图目录、输入法 id 全部走配置。

---

## 不同手机 / ROM 的注意事项

控件树、点击、截图这些依赖的是 Android 自带的 adb 能力，**换牌子基本都能用**；真正会因机型而异的是下面几处，遇到问题先照这张表查。

### 通用前提

| 项 | 说明 |
|---|---|
| Android 版本 | 6.0 及以上（`uiautomator` / `input` / `screencap` 都在） |
| USB 调试 | 开发者选项 → USB 调试，插线后允许 |
| 中文输入 | 必须装 [ADBKeyboard](https://github.com/senzhk/ADBKeyBoard)，并填对 `adb_keyboard_ime` |

### 各厂商的特殊开关

| 机型 / ROM | 现象 | 处理 |
|---|---|---|
| **小米 / 红米（MIUI、HyperOS）** | `input tap` 没反应 | 开发者选项里打开「**USB 调试（安全设置）**」，需要登录小米账号 |
| **华为 / 荣耀** | 输入/点击被拦 | 关闭「纯净模式」对调试的限制；部分系统要允许「USB 调试自动开启」 |
| **OPPO / vivo / 一加** | 控件树读不到 | 关闭「隐私保护 → 无障碍/屏幕读取」限制；vivo 需允许「USB 调试（安全设置）」 |
| **三星** | 点击可能有延迟 | 关闭「自适应电池」对 USB 的限制，或插电时操作 |
| **所有机型** | 锁屏 / 息屏时命令失败 | 先 `phone_key WAKEUP` 点亮屏幕并解锁 |
| **安卓 11+** | 无线调试连不上 | 先 `adb pair <ip>:<port>` 配对，再 `adb connect`，并填 `device_serial` |

### 输入框定位

`phone_tap_input` / `phone_type_input` 有两种定位方式：

1. **截图找白条**（首选）：原始截屏后沿屏幕底部找接近纯白的横条，跨手势导航 / 三键导航都适用；
2. **按比例试**：从 93% 屏高往下试几个位置，命不中再试（兜底）。

如果两种都没点中，会如实告诉你「没点中输入框」，这时用 `phone_look` 看一眼界面，再自己填坐标点。

### 分辨率与坐标

所有坐标都来自当次截屏 / 控件树，**不需要你手动换算**；手机分辨率、刘海、挖孔都不影响。

### 已知读不到的情况

| 情况 | 原因 | 替代 |
|---|---|---|
| 微信等应用控件树为空 | 应用主动屏蔽无障碍信息 | 自动改用 OCR |
| 小程序、网页、Flutter 页面 | 内容是一整块画布 | OCR（只能读屏幕上显示出来的字） |
| 图片里的文字 | OCR 可以读，但排版会损失 | 用 `phone_look` 发原图给人看 |
## 平台支持

| 系统 | 控件树 | OCR | 说明 |
|---|---|---|---|
| Windows | ✅ | ✅（系统自带 `Windows.Media.Ocr`） | 需要 `zh-Hans-CN` 语言包（中文系统默认有） |
| macOS / Linux | ✅ | ❌ | 没有系统级 OCR；可自行替换 `PhoneDevice.ocr()` |

---

## 已知限制

- **OCR 只能看到屏幕上真实渲染出来的字**：没显示出来的内容读不到。
- 部分应用（微信、部分 Flutter/WebView 页面）屏蔽控件树，只能走 OCR。
- 读取应用内部数据（聊天记录数据库等）**做不到**——那需要 root。
- 中文输入依赖 ADBKeyboard；没装就只能输入 ASCII。

---

## License

MIT
