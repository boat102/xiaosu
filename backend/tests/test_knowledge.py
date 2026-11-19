from app.knowledge import split_text


def test_split_text_keeps_content():
    text = "第一段\n" + ("这是测试内容。" * 200)
    parts = split_text(text, size=300, overlap=30)
    assert len(parts) > 1
    assert all(parts)
