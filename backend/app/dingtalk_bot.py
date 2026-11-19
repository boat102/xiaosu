"""DingTalk Stream-mode bot worker. Run with: uv run python -m app.dingtalk_bot"""
import logging
import threading
from collections import OrderedDict

import dingtalk_stream

from .agent import answer_chat
from .config import settings
from .database import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("xiaosu.dingtalk")

MAX_SEEN_MESSAGES = 1000
MAX_WORKERS = 4


def _answer(text: str, sender_id: str, conversation_id: str) -> dict:
    db = SessionLocal()
    try:
        return answer_chat(db, text, sender_id, "dingtalk", conversation_id)
    finally:
        db.close()


class XiaosuHandler(dingtalk_stream.AsyncChatbotHandler):
    """钉钉消息处理器。

    使用 AsyncChatbotHandler：SDK 先回 ACK，再把 process 放进线程池，LLM 调用不会阻塞
    Stream 心跳；reply_markdown 内部是同步 requests，也必须跑在线程里。
    """

    def __init__(self, max_workers: int = MAX_WORKERS):
        super().__init__(max_workers=max_workers)
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._seen_lock = threading.Lock()
        self._conversation_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def process(self, callback: dingtalk_stream.CallbackMessage):
        message = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        message_id = message.message_id or getattr(callback.headers, "message_id", None)
        if self._is_duplicate(message_id):
            logger.info("ignored duplicate message: %s", message_id)
            return

        # 群聊只在 @机器人 时响应；单聊始终响应。
        if message.conversation_type == "2" and message.is_in_at_list is False:
            return

        text = self._extract_text(message)
        if not text:
            if message.message_type in ("text", "richText"):
                self.reply_text("请发送具体问题。", message)
            else:
                self.reply_text("目前只支持文本问题，请用文字描述。", message)
            return

        sender_id = message.sender_staff_id or message.sender_id or "unknown"
        conversation_id = message.conversation_id or f"{message.conversation_type or 'unknown'}:{sender_id}"
        logger.info(
            "message sender=%s conversation=%s type=%s at=%s id=%s len=%s",
            sender_id, conversation_id, message.conversation_type,
            message.is_in_at_list, message_id, len(text),
        )
        try:
            with self._conversation_lock(conversation_id):
                result = _answer(text, sender_id, conversation_id)
            answer = result["answer"]
            if result["citations"]:
                refs = "\n\n**参考来源**\n" + "\n".join(
                    f"- {c['filename']}（段落 {c['ordinal'] + 1}）" for c in result["citations"]
                )
                answer += refs
            self.reply_markdown("小苏", answer, message)
        except Exception:
            logger.exception("DingTalk message failed")
            try:
                self.reply_text("小苏暂时遇到问题，请稍后重试。", message)
            except Exception:
                logger.exception("DingTalk fallback failed")

    def _extract_text(self, message: dingtalk_stream.ChatbotMessage) -> str:
        parts = message.get_text_list() or []
        text = "\n".join(part for part in parts if part).strip()
        bot_name = settings.dingtalk_bot_name.strip()
        if bot_name:
            text = text.replace(f"@{bot_name}", "").strip()
        return text

    def _is_duplicate(self, message_id: str | None) -> bool:
        if not message_id:
            return False
        with self._seen_lock:
            if message_id in self._seen:
                return True
            self._seen[message_id] = None
            while len(self._seen) > MAX_SEEN_MESSAGES:
                self._seen.popitem(last=False)
            return False

    def _conversation_lock(self, conversation_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._conversation_locks.setdefault(conversation_id, threading.Lock())


def main():
    if not settings.dingtalk_client_id or not settings.dingtalk_client_secret:
        raise SystemExit("请配置 DINGTALK_CLIENT_ID 和 DINGTALK_CLIENT_SECRET")
    if not settings.dingtalk_enabled:
        logger.warning("DINGTALK_ENABLED=false，仍以命令行方式启动；如需随 dev 脚本启动请设为 true")
    credential = dingtalk_stream.Credential(settings.dingtalk_client_id, settings.dingtalk_client_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(dingtalk_stream.ChatbotMessage.TOPIC, XiaosuHandler())
    logger.info("小苏钉钉 Stream Bot starting (bot_name=%s)", settings.dingtalk_bot_name)
    client.start_forever()


if __name__ == "__main__":
    main()
