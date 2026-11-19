from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import agent
from app.database import Base


class MockCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content="Mock LLM：已收到问题。", tool_calls=None)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice], usage=None)


class MockClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=MockCompletions())


def test_system_prompt_injects_current_date():
    now = datetime(2026, 11, 19, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    prompt = agent.build_system_prompt("测试上下文", now=now)
    assert "2026-11-19 星期四 10:30" in prompt
    assert "本周：2026-11-16 至 2026-11-22" in prompt
    assert "上周：2026-11-09 至 2026-11-15" in prompt
    assert "相对时间" in prompt
    assert "测试上下文" in prompt


def test_agent_uses_mock_llm_without_network(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    client = MockClient()
    monkeypatch.setattr(agent, "get_client", lambda: client)
    result = agent.answer_chat(db, "请做一个测试", "tester", "web", "mock-llm-test")
    assert result["answer"] == "Mock LLM：已收到问题。"
    system = client.chat.completions.calls[0]["messages"][0]["content"]
    assert "当前时间：" in system
    assert db.query(agent.Message).count() == 2
    db.close()
    Base.metadata.drop_all(engine)
