from app.tools import safe_calculate, execute_tool


def test_calculator_basic():
    assert safe_calculate("(2 + 3) * 4") == 20


def test_calculator_rejects_code():
    try:
        safe_calculate("__import__('os').system('whoami')")
        assert False, "unsafe expression should fail"
    except (ValueError, SyntaxError):
        assert True


def test_employee_mock_api():
    result = execute_tool("get_employee", {"employee_id": "001"})
    assert result["dept"] == "研发部"
