# 匿名倾诉转述插件 (astrbot_plugin_anon_relay)

一个 [AstrBot](https://github.com/AstrBotDevs/AstrBot)（v4，Star API）插件：
用户私聊机器人，**只有发送「开启匿名模式」才会建立会话**；之后用户的倾诉内容会被机器人
以匿名的身份**转述**到指定的群聊 —— 由机器人重新拼装成一条新消息发出（`匿名昵称 + 内容`），
**不是转发聊天记录**，群成员看不到任何真实身份信息。

## 特性

- 🔇 私聊开启匿名模式后才开始会话；未开启时机器人保持沉默（拦截私聊并阻止默认 LLM 回复）
- 🔄 消息转述：机器人以新消息形式（前缀 + 匿名昵称 + 内容）发到群聊，不转发原消息记录
- 🖼️ 支持文字与图片转述，长文自动分段
- 🎭 每个私聊用户分配稳定的匿名编号（如 `匿名者-001`），同一用户多次倾诉编号不变
- ⏱️ 可选会话空闲超时；会话状态持久化在插件 KV 存储中，重启不丢
- 🛠️ 专属插件设置面板：全部行为可在 WebUI 插件配置面板中调整（`_conf_schema.json` 自动生成表单）
- 📡 多平台：QQ / Telegram / 微信等均可（通过 AstrBot 统一消息通道发送）

## 安装

**方式一：下载 zip 上传安装（推荐，最简单）**

1. 下载安装包：https://github.com/yuntaojinghong/astrbot_plugin_anon_relay/releases/latest/download/astrbot_plugin_anon_relay.zip
   （zip 文件名必须保持为 `astrbot_plugin_anon_relay.zip`，AstrBot 以 zip 文件名作为插件目录名）
2. WebUI → 插件管理 → 安装插件 → 上传该 zip
3. 在插件管理中**重载插件**
4. 进入该插件的**配置面板**，填写「目标群号」，保存后再次重载插件生效

**方式二：手动复制文件夹**

1. 将 `astrbot_plugin_anon_relay` 整个文件夹复制到 AstrBot 的插件目录：
   - 桌面版：`C:\Users\<用户名>\.astrbot\data\plugins\`
   - 服务器版（源码/systemd）：`<AstrBot根目录>/data/plugins/`
   - Docker 版：容器内 `/AstrBot/data/plugins/`（或通过挂载卷放入宿主机对应目录）
2. 在 WebUI「插件管理」中**重载插件**。
3. 进入该插件的**配置面板**，填写「目标群号」，保存后再次重载插件生效。

**方式三：从 GitHub 仓库安装**

WebUI → 插件管理 → 安装插件 → 从 GitHub 仓库安装，填入
`https://github.com/yuntaojinghong/astrbot_plugin_anon_relay`（要求服务器能访问 GitHub）。

## 配置面板

WebUI → 插件管理 → 找到「匿名倾诉转述」→ 点击配置按钮。面板表单由插件目录下的
`_conf_schema.json` 自动生成，所有字段均可修改：

| 配置键 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 总开关，关闭后插件完全不响应 |
| `start_keywords` | `开启匿名模式` | 开启会话的关键词，多个用英文逗号分隔 |
| `stop_keywords` | `关闭匿名模式,结束倾诉` | 关闭会话的关键词 |
| `target_group_ids` | （空） | **必填**。目标群号，多个用英文逗号分隔（支持多群） |
| `relay_prefix` | `【匿名倾诉】` | 群内转述消息的前缀 |
| `relay_suffix` | （空） | 群内转述消息的后缀，如 `（来自匿名树洞）` |
| `anon_name_prefix` | `匿名者` | 匿名昵称前缀，自动编号：`匿名者-001` |
| `show_time` | `true` | 转述时附带时间（`MM-DD HH:MM`） |
| `ack_on_relay` | `true` | 每次转述成功后给倾诉者一条私聊回执 |
| `silent_when_off` | `true` | 未开启匿名模式时保持沉默；设为 `false` 则放行给其他处理器/LLM |
| `notify_group_on_start` | `false` | 有人开启匿名模式时在群内播报一条提示 |
| `max_msg_len` | `500` | 单条转述最大字数，超长自动分段发送 |
| `session_timeout_min` | `0` | 会话空闲超时（分钟），`0` 表示不超时 |

## 使用流程

```
用户私聊机器人：
  💬 开启匿名模式
  🤖 🔇 匿名模式已开启，你的匿名身份是「匿名者-001」…

  💬 最近工作压力好大，感觉快撑不住了……
  🤖 已为你转述 ✅
  （群聊里显示：）【匿名倾诉】匿名者-001 · 08-20 20:15 最近工作压力好大，感觉快撑不住了……

  💬 关闭匿名模式
  🤖 匿名模式已关闭。感谢你的信任，随时可以再来倾诉 🌱
```

未开启匿名模式时的私聊消息会被静默拦截（默认），机器人不会会话。

## 数据与隐私

- 插件只保存**会话状态**（用户平台标识 → 匿名编号、时间），**不保存聊天内容**。
- 数据存放在 AstrBot 的插件 KV 存储中（桌面版位于 `C:\Users\<用户名>\.astrbot\`）。
- 群内永远只出现匿名编号，不会出现真实昵称、QQ 号等身份信息。

## 常见问题

**私聊发消息没有反应？**
这是默认设计（`silent_when_off = true`）：不开启匿名模式就不会话。如需放行，把
`silent_when_off` 设为 `false`。

**群号填什么格式？**
QQ / OneBot 填群号数字即可；Telegram 填群聊 chat id（可能为负数）；多群用英文逗号分隔，如 `123456789,987654321`。

**转述失败？**
检查：目标群号是否正确、机器人是否在该群里、插件是否已重载、AstrBot 日志中是否有
`转述到群 ... 失败` 或 `未找到平台 ...` 报错。

**匿名编号会重复吗？**
编号全局递增并持久化，不会重复。如需重置所有匿名身份，可在 WebUI 插件配置中删除
插件数据，或联系管理员处理。

**旧版本 AstrBot 能用吗？**
本插件基于 AstrBot v4 Star API（`>= 4.16`），v3 及早期 v4 不支持。

## 文件结构

| 文件 | 用途 |
| --- | --- |
| `main.py` | 插件主体：`AnonRelay(Star)` 类，实现私聊拦截、关键词开启/关闭会话、匿名转述、长文分段、KV 持久化、主动发送到群聊 |
| `metadata.yaml` | 插件元数据：名称、显示名、简介、版本、作者、仓库地址、兼容的 AstrBot 版本范围；AstrBot 加载插件时读取 |
| `_conf_schema.json` | 插件设置面板 schema：WebUI「插件配置」的表单由此文件自动生成，每个键对应一个可编辑的配置项 |
| `README.md` | 本文档：安装、配置面板、使用流程、隐私说明与 FAQ |
| `LICENSE` | MIT 开源许可证，声明使用与分发条款 |
| `.gitignore` | Git 忽略规则：排除 `__pycache__` 等无关文件，保持仓库整洁 |
| `tests/test_logic.py` | 离线逻辑测试：用桩模块模拟 AstrBot API，无需安装 AstrBot 即可验证核心逻辑（`python -X utf8 tests/test_logic.py`） |

其中，AstrBot 真正运行只依赖三个文件：`main.py`、`metadata.yaml`、`_conf_schema.json`；
其余为开发与分发所需。

## 开发

- 修改 `main.py` 中的 `AnonRelayConfig` 默认值时，请同步更新 `_conf_schema.json` 的对应 `default`。
- 运行 `python -X utf8 tests/test_logic.py` 进行离线回归测试。
