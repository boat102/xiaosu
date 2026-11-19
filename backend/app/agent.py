import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .config import settings
from .knowledge import retrieve
from .models import Conversation, Message
from .tools import execute_tool, tool_definitions

SHANGHAI = ZoneInfo("Asia/Shanghai")

SYSTEM_PROMPT = """你是公司内部 AI 助手「小苏」。回答必须基于检索到的公司文档或工具结果。
当前时间：{now}。
本周：{this_week}；上周：{last_week}。
规则：1. 公司制度问题优先使用知识库，回答附带 [来源: 文件名 / 段落 N] 引用。
2. 知识库没有依据时明确说“文档里没找到相关内容”，不得猜测或编造。
3. 员工、考勤、订单、计算、时间问题应自主调用对应工具；不要伪造工具结果。
4. 涉及“今天/昨天/上周/本月”等相对时间时，直接使用上面给出的日期区间，不要自行推算；“最近一周/过去七天”按今天往前 7 天计算。
5. 只披露完成任务所需的最少员工信息。6. 回答使用中文，简洁清楚。
检索上下文：\n{context}"""


def build_system_prompt(context: str, now: datetime | None = None) -> str:
    current = now or datetime.now(SHANGHAI)
    monday = (current - timedelta(days=current.weekday())).date()
    last_monday = monday - timedelta(days=7)
    weekday = "一二三四五六日"[current.weekday()]
    return SYSTEM_PROMPT.format(
        now=f"{current:%Y-%m-%d} 星期{weekday} {current:%H:%M}",
        this_week=f"{monday} 至 {monday + timedelta(days=6)}",
        last_week=f"{last_monday} 至 {monday - timedelta(days=1)}",
        context=context or "无命中内容。",
    )


def get_client():
    if not settings.openai_api_key:
        return None
    from openai import OpenAI
    return OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)


def ensure_conversation(db: Session, user_id: str, channel: str, external_id: str):
    convo = db.query(Conversation).filter_by(user_id=user_id, channel=channel, external_conversation_id=external_id).first()
    if not convo:
        convo = Conversation(user_id=user_id, channel=channel, external_conversation_id=external_id)
        db.add(convo); db.commit(); db.refresh(convo)
    return convo


def answer_chat(db: Session, message: str, user_id: str, channel: str, external_id: str):
    client = get_client()
    convo = ensure_conversation(db, user_id, channel, external_id)
    history = db.query(Message).filter_by(conversation_id=convo.id).order_by(Message.id.desc()).limit(settings.max_history_messages).all()[::-1]
    citations = retrieve(db, message, client)
    context = "\n\n".join(f"[文件: {c['filename']} | 段落: {c['ordinal'] + 1}]\n{c['content']}" for c in citations)
    system = build_system_prompt(context)
    if not client:
        answer = "尚未配置 OPENAI_API_KEY，当前无法调用语言模型。请在 backend/.env 中配置后重试。"
        used, usage = [], {}
    else:
        messages = [{"role": "system", "content": system}]
        messages += [{"role": m.role, "content": m.content} for m in history if m.role in {"user", "assistant"}]
        messages.append({"role": "user", "content": message})
        used, usage = [], {}
        response = client.chat.completions.create(model=settings.openai_model, messages=messages,
            tools=tool_definitions(), tool_choice="auto", temperature=0.2)
        choice = response.choices[0]
        rounds = 0
        while choice.message.tool_calls and rounds < 5:
            messages.append(choice.message.model_dump(exclude_none=True))
            for call in choice.message.tool_calls:
                name = call.function.name
                try: args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError: args = {}
                result = execute_tool(name, args, db)
                used.append(name)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})
            response = client.chat.completions.create(model=settings.openai_model, messages=messages,
                tools=tool_definitions(), tool_choice="auto", temperature=0.2)
            choice = response.choices[0]; rounds += 1
        answer = choice.message.content or "暂时无法生成回答。"
        if response.usage:
            usage = {"prompt_tokens": response.usage.prompt_tokens, "completion_tokens": response.usage.completion_tokens,
                     "total_tokens": response.usage.total_tokens}
    db.add(Message(conversation_id=convo.id, role="user", content=message))
    db.add(Message(conversation_id=convo.id, role="assistant", content=answer, tool_names=used,
                   prompt_tokens=usage.get("prompt_tokens", 0), completion_tokens=usage.get("completion_tokens", 0)))
    db.commit()
    return {"answer": answer, "conversation_id": external_id, "citations": citations,
            "tools_used": used, "usage": usage}


def _stream_turn(client, messages):
    """Yield token events, then one internal tool_calls event for this model turn."""
    stream = client.chat.completions.create(
        model=settings.openai_model, messages=messages, tools=tool_definitions(),
        tool_choice="auto", temperature=0.2, stream=True,
    )
    calls = {}
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            yield {"type": "token", "content": delta.content}
        for part in (delta.tool_calls or []):
            item = calls.setdefault(part.index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            if part.id: item["id"] = part.id
            if part.function:
                if part.function.name: item["function"]["name"] += part.function.name
                if part.function.arguments: item["function"]["arguments"] += part.function.arguments
    yield {"type": "_tool_calls", "calls": [calls[i] for i in sorted(calls)]}


def stream_chat_events(db: Session, message: str, user_id: str, channel: str, external_id: str):
    """Stream actual model deltas while retaining the same tool and conversation behavior."""
    client = get_client()
    convo = ensure_conversation(db, user_id, channel, external_id)
    history = db.query(Message).filter_by(conversation_id=convo.id).order_by(Message.id.desc()).limit(settings.max_history_messages).all()[::-1]
    citations = retrieve(db, message, client)
    context = "\n\n".join(f"[文件: {c['filename']} | 段落: {c['ordinal'] + 1}]\n{c['content']}" for c in citations)
    messages = [{"role": "system", "content": build_system_prompt(context)}]
    messages += [{"role": m.role, "content": m.content} for m in history if m.role in {"user", "assistant"}]
    messages.append({"role": "user", "content": message})
    answer_parts, used = [], []
    if not client:
        fallback = "尚未配置 OPENAI_API_KEY，当前无法调用语言模型。请在 backend/.env 中配置后重试。"
        answer_parts.append(fallback)
        yield {"type": "token", "content": fallback}
    else:
        for _ in range(5):
            calls = []
            for event in _stream_turn(client, messages):
                if event["type"] == "token":
                    answer_parts.append(event["content"])
                    yield event
                else:
                    calls = event["calls"]
            if not calls:
                break
            messages.append({"role": "assistant", "content": None, "tool_calls": calls})
            for call in calls:
                name = call["function"]["name"]
                try: args = json.loads(call["function"]["arguments"] or "{}")
                except json.JSONDecodeError: args = {}
                result = execute_tool(name, args, db)
                used.append(name)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)})
    answer = "".join(answer_parts) or "暂时无法生成回答。"
    db.add(Message(conversation_id=convo.id, role="user", content=message))
    db.add(Message(conversation_id=convo.id, role="assistant", content=answer, tool_names=used))
    db.commit()
    yield {"type": "meta", "citations": citations, "tools_used": used, "conversation_id": external_id}
