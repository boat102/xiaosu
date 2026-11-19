import asyncio

from dingtalk_stream import AckMessage, CallbackMessage

from app import dingtalk_bot


class DummySession:
    def close(self):
        pass


def make_callback(text: str = "员工 001 是哪个部门的？") -> CallbackMessage:
    callback = CallbackMessage()
    callback.data = {
        "msgtype": "text",
        "text": {"content": text},
        "senderStaffId": "staff-001",
        "conversationId": "conversation-001",
        "sessionWebhook": "https://example.invalid/webhook",
    }
    return callback


def test_dingtalk_handler_replies_with_citations(monkeypatch):
    captured = {}
    monkeypatch.setattr(dingtalk_bot, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(
        dingtalk_bot,
        "answer_chat",
        lambda db, text, uid, channel, cid: {
            "answer": "员工 001 属于研发部。",
            "citations": [{"filename": "员工手册.md", "ordinal": 1}],
        },
    )
    handler = dingtalk_bot.XiaosuHandler()
    handler.reply_markdown = lambda title, text, message: captured.update(title=title, text=text)

    code, _ = asyncio.run(handler.process(make_callback()))

    assert code == AckMessage.STATUS_OK
    assert captured["title"] == "小苏"
    assert "员工 001 属于研发部。" in captured["text"]
    assert "员工手册.md（段落 2）" in captured["text"]


def test_dingtalk_handler_falls_back_on_error(monkeypatch):
    captured = {}

    def boom(*args, **kwargs):
        raise RuntimeError("model timeout")

    monkeypatch.setattr(dingtalk_bot, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(dingtalk_bot, "answer_chat", boom)
    handler = dingtalk_bot.XiaosuHandler()
    handler.reply_text = lambda text, message: captured.update(text=text)

    code, _ = asyncio.run(handler.process(make_callback()))

    assert code == AckMessage.STATUS_OK
    assert "稍后重试" in captured["text"]
