"""
匿名倾诉转述插件 (astrbot_plugin_anon_relay)
============================================

功能：
- 用户私聊机器人时，只有发送「开启匿名模式」（关键词可配置）才会建立会话；
  未开启时机器人保持沉默（默认拦截私聊，并阻止默认 LLM 回复）。
- 会话开启后，用户发送的文字/图片会被机器人以匿名的身份"转述"到指定的群聊：
  由机器人重新拼装成一条新消息（匿名昵称 + 内容）发出，而不是转发聊天记录，
  因此群成员看不到任何真实身份信息。
- 关闭关键词（默认「关闭匿名模式」「结束倾诉」）结束会话。
- 会话状态通过插件 KV 存储持久化，重启后依然有效。

基于 AstrBot v4（Star API，>= 4.16）开发。
"""

import logging
import re
import time
from dataclasses import MISSING, dataclass, fields

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star, register

logger = logging.getLogger("astrbot.plugin.anon_relay")

__version__ = "1.1.0"


@dataclass
class AnonRelayConfig:
    """代码级默认配置。WebUI 配置面板由 _conf_schema.json 生成，两者保持一致。"""

    enabled: bool = True                      # 总开关
    start_keywords: str = "开启匿名模式"       # 开启匿名模式的关键词（逗号分隔多个）
    stop_keywords: str = "关闭匿名模式,结束倾诉"  # 关闭会话的关键词（逗号分隔多个）
    target_group_ids: str = ""                # 目标群号，多个用英文逗号分隔（支持多群）
    relay_prefix: str = "【匿名倾诉】"          # 群内转述消息的前缀
    relay_suffix: str = ""                    # 群内转述消息的后缀（如：（来自匿名树洞））
    anon_name_prefix: str = "匿名者"           # 匿名昵称前缀，自动编号，如 匿名者-001
    show_time: bool = True                    # 转述时附带时间
    ack_on_relay: bool = True                 # 转述成功后私聊回执
    silent_when_off: bool = True              # 未开启匿名模式时保持沉默（拦截私聊，不回复）
    notify_group_on_start: bool = False       # 开启匿名模式时在群内播报一条提示
    max_msg_len: int = 500                    # 单条转述最大字数，超长自动分段发送
    session_timeout_min: int = 0              # 会话空闲超时（分钟），0 为不超时


@register("astrbot_plugin_anon_relay", "guishe", "匿名倾诉转述：私聊开启匿名模式后，将内容以匿名身份转述到指定群聊", __version__)
class AnonRelay(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = self._merge_config(config)
        self.plugin_id = getattr(self, "plugin_id", None) or "anon_relay"
        self.logger = getattr(self, "logger", None) or logger
        self.sessions = {}
        self.counter = 0
        self._kv_loaded = False

    # ------------------------------------------------------------------ #
    # 配置
    # ------------------------------------------------------------------ #

    @staticmethod
    def _default_config() -> dict:
        return {f.name: f.default for f in fields(AnonRelayConfig) if f.default is not MISSING}

    @classmethod
    def _merge_config(cls, config):
        """兼容 dict（含 AstrBotConfig）与 dataclass 两种配置对象。"""
        defaults = cls._default_config()
        if isinstance(config, dict):
            return {**defaults, **config}
        d = getattr(config, "__dict__", None)
        if isinstance(d, dict):
            merged = dict(defaults)
            for k, v in d.items():
                if not k.startswith("_"):
                    merged[k] = v
            return merged
        return dict(defaults)

    def _cfg(self, key):
        v = self.config.get(key)
        if v is None:
            return self._default_config().get(key)
        return v

    def _cfg_bool(self, key):
        v = self._cfg(key)
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on", "是", "开")
        return bool(v)

    def _cfg_int(self, key):
        try:
            return int(self._cfg(key))
        except (TypeError, ValueError):
            return 0

    # ------------------------------------------------------------------ #
    # 会话持久化（插件 KV 存储）
    # ------------------------------------------------------------------ #

    async def _ensure_kv_loaded(self):
        if self._kv_loaded:
            return
        try:
            self.sessions = dict(await self.get_kv_data("sessions", {}) or {})
            self.counter = int(await self.get_kv_data("counter", 0) or 0)
        except Exception as e:
            self.logger.warning("读取插件存储失败，本次运行会话数据仅保存在内存: %s", e)
        self._kv_loaded = True

    async def _save_sessions(self):
        try:
            await self.put_kv_data("sessions", self.sessions)
            await self.put_kv_data("counter", self.counter)
        except Exception as e:
            self.logger.warning("保存会话数据失败: %s", e)

    # ------------------------------------------------------------------ #
    # 消息入口：匹配所有消息，仅处理私聊
    # ------------------------------------------------------------------ #

    @filter.regex(r"[\s\S]*")
    async def on_message(self, event: AstrMessageEvent):
        if not self._cfg_bool("enabled"):
            return
        if not self._is_private_chat(event):
            return
        await self._ensure_kv_loaded()
        key = self._user_key(event)
        text = event.get_message_str().strip()
        reply, consume = await self._handle(event, key, text)
        if consume:
            self._stop_event(event)
            self._block_default_llm(event)
        if reply:
            yield event.plain_result(reply)

    async def _handle(self, event, key, text):
        if self._contains_keyword(text, self._cfg("start_keywords")):
            return await self._start_session(event, key)
        if self._contains_keyword(text, self._cfg("stop_keywords")):
            return await self._stop_session(key)
        if key in self.sessions:
            if self._session_expired(key):
                return await self._expire_session(key)
            return await self._relay(event, key)
        # 未开启匿名模式：按配置决定是否保持沉默
        if self._cfg_bool("silent_when_off"):
            return None, True
        return None, False

    # ------------------------------------------------------------------ #
    # 会话控制
    # ------------------------------------------------------------------ #

    async def _start_session(self, event, key):
        if key in self.sessions:
            return "你已处于匿名模式，直接发送内容即可。", True
        groups = self._target_groups()
        if not groups:
            return "⚠️ 管理员还未在插件设置中填写「目标群号」，暂时无法开启匿名模式。", True
        self.counter += 1
        prefix = str(self._cfg("anon_name_prefix") or "匿名者")
        anon_id = f"{prefix}-{self.counter:03d}"
        self.sessions[key] = {
            "anon_id": anon_id,
            "started_at": time.time(),
            "last_active": time.time(),
        }
        await self._save_sessions()
        if self._cfg_bool("notify_group_on_start"):
            await self._send_to_groups(groups, event, [Plain(text=self._relay_header(anon_id) + " 已开启匿名倾诉")])
        return (
            f"🔇 匿名模式已开启，你的匿名身份是「{anon_id}」\n"
            "现在可以开始倾诉了，我会把你的内容匿名转述到指定群聊。\n"
            f"发送「{str(self._cfg('stop_keywords')).split(',')[0]}」即可结束。"
        ), True

    async def _stop_session(self, key):
        if key not in self.sessions:
            return "你当前没有开启匿名模式。", True
        self.sessions.pop(key, None)
        await self._save_sessions()
        return "匿名模式已关闭。感谢你的信任，随时可以再来倾诉 🌱", True

    async def _expire_session(self, key):
        self.sessions.pop(key, None)
        await self._save_sessions()
        return "会话已超时自动结束，如需继续请重新发送开启关键词。", True

    def _session_expired(self, key):
        timeout = self._cfg_int("session_timeout_min")
        if timeout <= 0:
            return False
        s = self.sessions.get(key)
        if not s:
            return False
        return (time.time() - float(s.get("last_active", 0) or 0)) > timeout * 60

    # ------------------------------------------------------------------ #
    # 转述
    # ------------------------------------------------------------------ #

    async def _relay(self, event, key):
        session = self.sessions.get(key)
        if not session:
            return None, True
        chain = self._get_message_chain(event)
        parts = [c for c in chain if isinstance(c, (Plain, Image))]
        if not parts:
            return "暂不支持转述这类消息（仅支持文字和图片）。", True
        groups = self._target_groups()
        if not groups:
            return "⚠️ 目标群聊未配置，无法转述，请联系管理员。", True

        text = event.get_message_str().strip()
        images = [c for c in parts if isinstance(c, Image)]
        header = self._relay_header(session["anon_id"])
        max_len = self._cfg_int("max_msg_len") or 500
        msgs = self._build_relay_messages(header, text, images, max_len)

        ok = True
        for gid in groups:
            for m in msgs:
                if not await self._send_group(event, gid, m):
                    ok = False

        session["last_active"] = time.time()
        await self._save_sessions()

        if not ok:
            return "⚠️ 转述失败，请稍后重试。", True
        if self._cfg_bool("ack_on_relay"):
            return "已为你转述 ✅", True
        return None, True

    def _relay_header(self, anon_id):
        parts = [str(self._cfg("relay_prefix") or ""), anon_id]
        if self._cfg_bool("show_time"):
            parts.append(time.strftime("%m-%d %H:%M", time.localtime()))
        suffix = str(self._cfg("relay_suffix") or "").strip()
        if suffix:
            parts.append(suffix)
        return " ".join(p for p in parts if p)

    @staticmethod
    def _build_relay_messages(header, text, images, max_len):
        """把转述内容组装为一条或多条（长文分段）新消息。"""
        chunks = AnonRelay._split_text(text, max_len)
        msgs = []
        if not chunks:
            msgs.append([Plain(text=header), *images])
            return msgs
        for i, chunk in enumerate(chunks):
            comps = []
            if i == 0:
                comps.append(Plain(text=header))
            comps.append(Plain(text=chunk))
            if i == len(chunks) - 1:
                comps.extend(images)
            msgs.append(comps)
        return msgs

    @staticmethod
    def _split_text(text, max_len):
        text = (text or "").strip()
        if not text:
            return []
        if len(text) <= max_len:
            return [text]
        return [text[i:i + max_len] for i in range(0, len(text), max_len)]

    # ------------------------------------------------------------------ #
    # 发送
    # ------------------------------------------------------------------ #

    async def _send_to_groups(self, groups, event, chain):
        ok = True
        for gid in groups:
            if not await self._send_group(event, gid, chain):
                ok = False
        return ok

    async def _send_group(self, event, group_id, chain):
        """通过 Context.send_message 主动发送到指定群聊（v4 官方通道）。"""
        session_str = f"{event.get_platform_id()}:GroupMessage:{group_id}"
        try:
            ok = await self.context.send_message(session_str, chain)
            if not ok:
                self.logger.error("未找到平台 %s，无法转述到群 %s", event.get_platform_id(), group_id)
            return bool(ok)
        except Exception as e:
            self.logger.error("转述到群 %s 失败: %s", group_id, e)
            return False

    # ------------------------------------------------------------------ #
    # 工具方法
    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_message_chain(event):
        fn = getattr(event, "get_messages", None) or getattr(event, "get_message", None)
        return fn() if fn else []

    @staticmethod
    def _is_private_chat(event):
        try:
            if hasattr(event, "is_private_chat"):
                return bool(event.is_private_chat())
        except Exception:
            pass
        try:
            mo = getattr(event, "message_obj", None)
            if mo is not None:
                return getattr(mo, "group_id", None) is None
        except Exception:
            pass
        origin = str(getattr(event, "unified_msg_origin", "") or "")
        return "friend" in origin.lower() or "private" in origin.lower()

    @staticmethod
    def _user_key(event):
        return f"{event.get_platform_name()}:{event.get_sender_id()}"

    @staticmethod
    def _stop_event(event):
        try:
            event.stop_event()
        except Exception:
            pass

    @staticmethod
    def _block_default_llm(event):
        try:
            event.should_call_llm(False)
        except Exception:
            pass

    @staticmethod
    def _contains_keyword(text, keywords):
        if not text or not keywords:
            return False
        for kw in re.split(r"[,，、;；]+", str(keywords)):
            if kw and kw in text:
                return True
        return False

    def _target_groups(self):
        raw = str(self._cfg("target_group_ids") or "")
        groups = []
        for part in re.split(r"[,，、;；\s]+", raw):
            p = part.strip()
            if p and p not in groups:
                groups.append(p)
        return groups
