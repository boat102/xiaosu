from dingtalk_stream import CallbackMessage

from app import dingtalk_bot


class DummySession:
    def close(self):
        pass


def make_callback(
    text: str = "员工 001 是哪个部门的？",
    message_id: str = "msg-1",
    conversation_type: str = "1",
    is_in_at_list: bool = True,
    msg_type: str = "text",
) -> CallbackMessage:
    callback = CallbackMessage()
    callback.data = {
        "msgtype": msg_type,
        "senderStaffId": "staff-001",
        "conversationId": "conversation-001",
        "conversationType": conversation_type,
        "isInAtList": is_in_at_list,
        "msgId": message_id,
        "sessionWebhook": "https://example.invalid/webhook",
    }
    if msg_type == "text":
        callback.data["text"] = {"content": text}
    elif msg_type == "richText":
        callback.data["content"] = {"richText": [{"text": text}]}
    elif msg_type == "picture":
        callback.data["content"] = {"downloadCode": "img-1"}
    return callback


def patch_answer(monkeypatch, *, result=None, calls=None):
    monkeypatch.setattr(dingtalk_bot, "SessionLocal", lambda: DummySession())

    def fake(db, text, uid, channel, cid):
        if calls is not None:
            calls.append(text)
        return result or {
            "answer": "员工 001 属于研发部。",
            "citations": [{"filename": "员工手册.md", "ordinal": 1}],
        }

    monkeypatch.setattr(dingtalk_bot, "answer_chat", fake)


def test_dingtalk_handler_replies_with_citations(monkeypatch):
    captured = {}
    patch_answer(monkeypatch)
    handler = dingtalk_bot.XiaosuHandler()
    handler.reply_markdown = lambda title, text, message: captured.update(title=title, text=text)

    handler.process(make_callback())

    assert captured["title"] == "小苏"
    assert "员工 001 属于研发部。" in captured["text"]
    assert "员工手册.md（段落 2）" in captured["text"]


def test_dingtalk_handler_falls_back_on_error(monkeypatch):
    captured = {}
    monkeypatch.setattr(dingtalk_bot, "SessionLocal", lambda: DummySession())

    def boom(*args, **kwargs):
        raise RuntimeError("model timeout")

    monkeypatch.setattr(dingtalk_bot, "answer_chat", boom)
    handler = dingtalk_bot.XiaosuHandler()
    handler.reply_text = lambda text, message: captured.update(text=text)

    handler.process(make_callback())

    assert "稍后重试" in captured["text"]


def test_dingtalk_group_message_without_at_is_ignored(monkeypatch):
    replies = []
    patch_answer(monkeypatch)
    handler = dingtalk_bot.XiaosuHandler()
    handler.reply_markdown = lambda *args: replies.append(args)
    handler.reply_text = lambda *args: replies.append(args)

    handler.process(make_callback(conversation_type="2", is_in_at_list=False))

    assert replies == []


def test_dingtalk_duplicate_message_is_ignored(monkeypatch):
    replies = []
    patch_answer(monkeypatch)
    handler = dingtalk_bot.XiaosuHandler()
    handler.reply_markdown = lambda *args: replies.append(args)

    handler.process(make_callback(message_id="msg-same"))
    handler.process(make_callback(message_id="msg-same"))

    assert len(replies) == 1


def test_dingtalk_non_text_gets_hint(monkeypatch):
    captured = {}
    patch_answer(monkeypatch)
    handler = dingtalk_bot.XiaosuHandler()
    handler.reply_text = lambda text, message: captured.update(text=text)

    handler.process(make_callback(msg_type="picture"))

    assert "只支持文本" in captured["text"]


def test_dingtalk_strips_bot_mention(monkeypatch):
    calls = []
    patch_answer(monkeypatch, calls=calls)
    handler = dingtalk_bot.XiaosuHandler()
    handler.reply_markdown = lambda *args: None

    handler.process(make_callback(text="@小苏 员工 001 是哪个部门的？"))

    assert calls == ["员工 001 是哪个部门的？"]


def test_dingtalk_richtext_is_answered(monkeypatch):
    calls = []
    patch_answer(monkeypatch, calls=calls)
    handler = dingtalk_bot.XiaosuHandler()
    handler.reply_markdown = lambda *args: None

    handler.process(make_callback(text="年假有几天？", msg_type="richText"))

    assert calls == ["年假有几天？"]
