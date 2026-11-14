from datetime import date

import pytest

from studytask import create_app
from studytask.db import get_db


def task_data(**overrides):
    data = {
        "name": "完成软件工程实验报告",
        "course": "软件工程",
        "description": "包含需求分析、实现与测试记录",
        "due_date": "2026-11-20",
        "priority": "高",
        "status": "待完成",
    }
    data.update(overrides)
    return data


def create_task(client, **overrides):
    response = client.post("/tasks/new", data=task_data(**overrides))
    assert response.status_code == 302
    return int(response.headers["Location"].rstrip("/").split("/")[-1])


def stored_task(app, task_id):
    with app.app_context():
        row = get_db().execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None


def test_t1_create_task_with_all_fields(client, app):
    task_id = create_task(
        client,
        name="  完成需求分析  ",
        course="  软件工程  ",
        description="整理功能需求",
        due_date="2026-11-16",
        priority="高",
        status="进行中",
    )

    task = stored_task(app, task_id)
    assert task["name"] == "完成需求分析"
    assert task["course"] == "软件工程"
    assert task["description"] == "整理功能需求"
    assert task["due_date"] == "2026-11-16"
    assert task["priority"] == "高"
    assert task["status"] == "进行中"
    assert task["created_at"]
    assert task["updated_at"]
    detail = client.get(f"/tasks/{task_id}")
    assert detail.status_code == 200
    assert "任务创建成功" in detail.get_data(as_text=True)


def test_t2_empty_name_is_rejected(client, app):
    response = client.post("/tasks/new", data=task_data(name="   "))

    assert response.status_code == 400
    assert "任务名称不能为空" in response.get_data(as_text=True)
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_t3_edit_task(client, app):
    task_id = create_task(client)
    original = stored_task(app, task_id)

    response = client.post(
        f"/tasks/{task_id}/edit",
        data=task_data(
            name="修改后的实验报告",
            course="软件质量保障",
            description="补充验收结果",
            due_date="2026-11-18",
            priority="中",
            status="进行中",
        ),
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/tasks/{task_id}")
    updated = stored_task(app, task_id)
    assert updated["name"] == "修改后的实验报告"
    assert updated["course"] == "软件质量保障"
    assert updated["description"] == "补充验收结果"
    assert updated["due_date"] == "2026-11-18"
    assert updated["priority"] == "中"
    assert updated["status"] == "进行中"
    assert updated["created_at"] == original["created_at"]


def test_t4_update_status(client, app):
    task_id = create_task(client, status="待完成")

    response = client.post(f"/tasks/{task_id}/status", data={"status": "已完成"})

    assert response.status_code == 302
    assert stored_task(app, task_id)["status"] == "已完成"
    page = client.get(f"/tasks/{task_id}").get_data(as_text=True)
    assert "任务状态已更新" in page
    assert "已完成" in page


def test_t5_single_and_combined_filters(client):
    create_task(client, name="软件工程高优先级待办", course="软件工程", priority="高", status="待完成")
    create_task(client, name="软件工程已完成任务", course="软件工程", priority="高", status="已完成")
    create_task(client, name="数据库中优先级任务", course="数据库", priority="中", status="待完成")

    single = client.get("/?course=软件工程").get_data(as_text=True)
    assert "软件工程高优先级待办" in single
    assert "软件工程已完成任务" in single
    assert "数据库中优先级任务" not in single
    assert "当前显示 2 项" in single

    combined = client.get("/?course=软件工程&status=待完成&priority=高").get_data(as_text=True)
    assert "软件工程高优先级待办" in combined
    assert "软件工程已完成任务" not in combined
    assert "数据库中优先级任务" not in combined
    assert "当前显示 1 项" in combined


@pytest.mark.parametrize("status", ["待完成", "进行中"])
def test_t6_unfinished_yesterday_task_is_overdue(client, status):
    task_id = create_task(client, due_date="2026-11-13", status=status)

    page = client.get(f"/tasks/{task_id}").get_data(as_text=True)

    assert 'class="badge reminder-overdue"' in page
    assert "逾期" in page


def test_t6_completed_yesterday_task_has_no_reminder(client):
    task_id = create_task(client, due_date="2026-11-13", status="已完成")

    page = client.get(f"/tasks/{task_id}").get_data(as_text=True)

    assert "reminder-overdue" not in page
    assert "reminder-upcoming" not in page


def test_t7_tomorrow_task_is_upcoming(client):
    task_id = create_task(client, due_date="2026-11-15", status="待完成")

    page = client.get(f"/tasks/{task_id}").get_data(as_text=True)

    assert 'class="badge reminder-upcoming"' in page
    assert "即将到期" in page


@pytest.mark.parametrize(
    ("due_date", "status", "expected_reminder"),
    [
        ("2026-11-14", "待完成", "reminder-upcoming"),
        ("2026-11-17", "进行中", "reminder-upcoming"),
        ("2026-11-18", "待完成", None),
        ("2026-11-15", "已完成", None),
    ],
)
def test_due_date_boundaries_and_completed_tasks(client, due_date, status, expected_reminder):
    task_id = create_task(client, due_date=due_date, status=status)

    page = client.get(f"/tasks/{task_id}").get_data(as_text=True)

    if expected_reminder:
        assert expected_reminder in page
    else:
        assert "reminder-upcoming" not in page
        assert "reminder-overdue" not in page


def test_t8_global_statistics_and_completion_rate(client):
    create_task(client, name="任务一", status="已完成")
    create_task(client, name="任务二", status="已完成")
    create_task(client, name="任务三", status="进行中")
    create_task(client, name="任务四", status="待完成")
    create_task(client, name="任务五", status="待完成")

    page = client.get("/?status=待完成").get_data(as_text=True)

    assert '<span class="stat-label">全部任务</span><strong>5</strong>' in page
    assert '<span class="stat-label">已完成</span><strong>2</strong>' in page
    assert '<strong>40<span class="rate-unit">%</span></strong>' in page
    assert "当前显示 2 项" in page


def test_t9_delete_cancel_then_confirm(client, app):
    task_id = create_task(client, name="需要删除的任务")

    confirmation = client.get(f"/tasks/{task_id}/delete")
    assert confirmation.status_code == 200
    assert "确认删除这项任务" in confirmation.get_data(as_text=True)

    cancel = client.post(f"/tasks/{task_id}/delete", data={"action": "cancel"})
    assert cancel.status_code == 302
    assert stored_task(app, task_id) is not None

    confirm = client.post(f"/tasks/{task_id}/delete", data={"action": "confirm"})
    assert confirm.status_code == 302
    assert confirm.headers["Location"].endswith("/")
    assert stored_task(app, task_id) is None
    assert client.get(f"/tasks/{task_id}").status_code == 404


def test_t10_data_survives_application_restart(tmp_path):
    database = str(tmp_path / "restart.sqlite3")
    config = {
        "TESTING": True,
        "SECRET_KEY": "test",
        "DATABASE": database,
        "TODAY_PROVIDER": lambda: date(2026, 11, 14),
    }
    first_app = create_app(config)
    first_client = first_app.test_client()
    task_id = create_task(first_client, name="重启后仍存在的任务", description="持久化验收")

    second_app = create_app(config)
    second_client = second_app.test_client()
    page = second_client.get(f"/tasks/{task_id}")

    assert page.status_code == 200
    assert "重启后仍存在的任务" in page.get_data(as_text=True)
    assert stored_task(second_app, task_id)["description"] == "持久化验收"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", "任" * 101, "任务名称不能超过100字"),
        ("course", "", "所属课程不能为空"),
        ("course", "课" * 61, "所属课程不能超过60字"),
        ("description", "述" * 1001, "任务描述不能超过1000字"),
        ("due_date", "2026/11/14", "请输入YYYY-MM-DD格式的截止日期"),
        ("due_date", "2026-02-30", "截止日期不是有效日期"),
        ("priority", "紧急", "请选择有效的优先级"),
        ("status", "已归档", "请选择有效的任务状态"),
    ],
)
def test_invalid_fields_are_rejected(client, app, field, value, message):
    response = client.post("/tasks/new", data=task_data(**{field: value}))

    assert response.status_code == 400
    assert message in response.get_data(as_text=True)
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_invalid_direct_status_update_is_rejected(client, app):
    task_id = create_task(client, status="待完成")

    response = client.post(f"/tasks/{task_id}/status", data={"status": "已归档"})

    assert response.status_code == 400
    assert "请选择有效的任务状态" in response.get_data(as_text=True)
    assert stored_task(app, task_id)["status"] == "待完成"


def test_missing_task_uses_chinese_404_page(client):
    response = client.get("/tasks/999")

    assert response.status_code == 404
    assert "没有找到这个页面" in response.get_data(as_text=True)
