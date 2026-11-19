"""DingTalk Stream-mode bot worker. Run with: uv run python -m app.dingtalk_bot"""
import asyncio
import logging

import dingtalk_stream

from .agent import answer_chat
from .config import settings
from .database import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("xiaosu.dingtalk")


def _answer(text: str, sender_id: str, conversation_id: str) -> dict:
    db = SessionLocal()
    try:
        return answer_chat(db, text, sender_id, "dingtalk", conversation_id)
    finally:
        db.close()


class XiaosuHandler(dingtalk_stream.ChatbotHandler):
    async def process(self, callback: dingtalk_stream.CallbackMessage):
        message = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        text = (message.text.content or "").strip() if message.text else ""
        if not text:
            return dingtalk_stream.AckMessage.STATUS_OK, ""
        sender_id = message.sender_staff_id or message.sender_id or "unknown"
        conversation_id = message.conversation_id or "default"
        try:
            result = await asyncio.to_thread(_answer, text, sender_id, conversation_id)
            answer = result["answer"]
            if result["citations"]:
                refs = "\n\n**参考来源**\n" + "\n".join(f"- {c['filename']}（段落 {c['ordinal'] + 1}）" for c in result["citations"])
                answer += refs
            self.reply_markdown("小苏", answer, message)
        except Exception:
            logger.exception("DingTalk message failed")
            try:
                self.reply_text("小苏暂时遇到问题，请稍后重试。", message)
            except Exception: logger.exception("DingTalk fallback failed")
        return dingtalk_stream.AckMessage.STATUS_OK, ""


def main():
    if not settings.dingtalk_client_id or not settings.dingtalk_client_secret:
        raise SystemExit("请配置 DINGTALK_CLIENT_ID 和 DINGTALK_CLIENT_SECRET")
    credential = dingtalk_stream.Credential(settings.dingtalk_client_id, settings.dingtalk_client_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(dingtalk_stream.ChatbotMessage.TOPIC, XiaosuHandler())
    logger.info("小苏钉钉 Stream Bot starting")
    client.start_forever()


if __name__ == "__main__": main()
