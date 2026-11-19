import ast
import operator
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .models import ToolAudit

EMPLOYEES = [
    {"id": "001", "name": "张三", "dept": "研发部", "level": "P5"},
    {"id": "002", "name": "李四", "dept": "销售部", "level": "P6"},
    {"id": "003", "name": "王五", "dept": "人力资源部", "level": "P4"},
]
ATTENDANCE = [
    {"emp_id": "001", "date": "2026-11-09", "check_in": "09:02", "check_out": "18:05"},
    {"emp_id": "001", "date": "2026-11-10", "check_in": "09:08", "check_out": "18:20"},
    {"emp_id": "001", "date": "2026-11-11", "check_in": "09:12", "check_out": "18:15"},
    {"emp_id": "001", "date": "2026-11-12", "check_in": "09:00", "check_out": "18:30"},
    {"emp_id": "001", "date": "2026-11-13", "check_in": "09:20", "check_out": "18:10"},
    {"emp_id": "001", "date": "2026-11-16", "check_in": "09:05", "check_out": "18:10"},
    {"emp_id": "001", "date": "2026-11-17", "check_in": "09:15", "check_out": "18:30"},
    {"emp_id": "001", "date": "2026-11-18", "check_in": "08:58", "check_out": "18:20"},
    {"emp_id": "002", "date": "2026-11-09", "check_in": "09:03", "check_out": "18:02"},
    {"emp_id": "002", "date": "2026-11-11", "check_in": "09:10", "check_out": "18:08"},
    {"emp_id": "002", "date": "2026-11-13", "check_in": "09:06", "check_out": "18:12"},
    {"emp_id": "002", "date": "2026-11-17", "check_in": "09:00", "check_out": "18:00"},
]
ORDERS = [
    {"id": "O2026111601", "amount": 1280, "date": "2026-11-16", "status": "paid"},
    {"id": "O2026111701", "amount": 2580, "date": "2026-11-17", "status": "paid"},
    {"id": "O2026111702", "amount": 800, "date": "2026-11-17", "status": "refunded"},
    {"id": "O2026111801", "amount": 3600, "date": "2026-11-18", "status": "paid"},
]

_ALLOWED = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
            ast.Mod: operator.mod}


def safe_calculate(expression: str):
    if len(expression) > 100:
        raise ValueError("表达式过长")
    def visit(node):
        if isinstance(node, ast.Expression): return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)): return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED:
            return _ALLOWED[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED:
            return _ALLOWED[type(node.op)](visit(node.operand))
        raise ValueError("不支持的数学表达式")
    return visit(ast.parse(expression, mode="eval"))


def tool_definitions():
    return [
        {"type": "function", "function": {"name": "get_employee", "description": "按员工编号查询员工部门和职级", "parameters": {"type": "object", "properties": {"employee_id": {"type": "string"}}, "required": ["employee_id"]}}},
        {"type": "function", "function": {"name": "get_attendance", "description": "查询员工某日期范围的考勤记录", "parameters": {"type": "object", "properties": {"employee_id": {"type": "string"}, "start_date": {"type": "string"}, "end_date": {"type": "string"}}, "required": ["employee_id"]}}},
        {"type": "function", "function": {"name": "get_orders", "description": "查询订单并统计已支付订单销售额，可按日期过滤", "parameters": {"type": "object", "properties": {"start_date": {"type": "string"}, "end_date": {"type": "string"}}, "required": []}}},
        {"type": "function", "function": {"name": "calculate", "description": "计算简单数学表达式", "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}}},
        {"type": "function", "function": {"name": "current_time", "description": "获取当前时间", "parameters": {"type": "object", "properties": {"timezone": {"type": "string", "default": "Asia/Shanghai"}}, "required": []}}},
    ]


def execute_tool(name: str, args: dict, db: Session | None = None):
    if name == "get_employee":
        result = next((e for e in EMPLOYEES if e["id"] == args["employee_id"]), {"error": "未找到该员工"})
    elif name == "get_attendance":
        rows = [r for r in ATTENDANCE if r["emp_id"] == args["employee_id"]]
        if args.get("start_date"): rows = [r for r in rows if r["date"] >= args["start_date"]]
        if args.get("end_date"): rows = [r for r in rows if r["date"] <= args["end_date"]]
        result = {"records": rows, "days_present": len(rows)}
    elif name == "get_orders":
        rows = [r for r in ORDERS if r["status"] == "paid"]
        if args.get("start_date"): rows = [r for r in rows if r["date"] >= args["start_date"]]
        if args.get("end_date"): rows = [r for r in rows if r["date"] <= args["end_date"]]
        result = {"orders": rows, "order_count": len(rows), "sales_total": sum(r["amount"] for r in rows)}
    elif name == "calculate": result = {"result": safe_calculate(args["expression"])}
    elif name == "current_time":
        tz = ZoneInfo(args.get("timezone", "Asia/Shanghai"))
        result = {"time": datetime.now(tz).isoformat(), "timezone": str(tz)}
    else: result = {"error": "未知工具"}
    if db:
        db.add(ToolAudit(tool_name=name, input_json=args, output_text=str(result), success="error" not in result))
        db.commit()
    return result
