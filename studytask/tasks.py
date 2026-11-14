import re
from datetime import date, datetime

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for

from .db import get_db

bp = Blueprint("tasks", __name__)

PRIORITIES = ("高", "中", "低")
STATUSES = ("待完成", "进行中", "已完成")
PRIORITY_CLASSES = {"高": "high", "中": "medium", "低": "low"}
STATUS_CLASSES = {"待完成": "pending", "进行中": "progress", "已完成": "completed"}


def current_timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def validate_task(form):
    data = {
        "name": form.get("name", "").strip(),
        "course": form.get("course", "").strip(),
        "description": form.get("description", "").strip(),
        "due_date": form.get("due_date", "").strip(),
        "priority": form.get("priority", "中"),
        "status": form.get("status", "待完成"),
    }
    errors = {}

    if not data["name"]:
        errors["name"] = "任务名称不能为空。"
    elif len(data["name"]) > 100:
        errors["name"] = "任务名称不能超过100字。"

    if not data["course"]:
        errors["course"] = "所属课程不能为空。"
    elif len(data["course"]) > 60:
        errors["course"] = "所属课程不能超过60字。"

    if len(data["description"]) > 1000:
        errors["description"] = "任务描述不能超过1000字。"

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["due_date"]):
        errors["due_date"] = "请输入YYYY-MM-DD格式的截止日期。"
    else:
        try:
            date.fromisoformat(data["due_date"])
        except ValueError:
            errors["due_date"] = "截止日期不是有效日期。"

    if data["priority"] not in PRIORITIES:
        errors["priority"] = "请选择有效的优先级。"

    if data["status"] not in STATUSES:
        errors["status"] = "请选择有效的任务状态。"

    return data, errors


def get_task(task_id):
    task = get_db().execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        abort(404)
    return task


def with_reminder(task):
    item = dict(task)
    item["priority_class"] = PRIORITY_CLASSES[item["priority"]]
    item["status_class"] = STATUS_CLASSES[item["status"]]
    item["reminder"] = None
    item["reminder_label"] = ""

    if item["status"] != "已完成":
        today = current_app.config["TODAY_PROVIDER"]()
        due_date = date.fromisoformat(item["due_date"])
        days_left = (due_date - today).days
        if days_left < 0:
            item["reminder"] = "overdue"
            item["reminder_label"] = "逾期"
        elif days_left <= 3:
            item["reminder"] = "upcoming"
            item["reminder_label"] = "即将到期"

    return item


@bp.route("/")
def index():
    filters = {
        "course": request.args.get("course", "").strip(),
        "status": request.args.get("status", ""),
        "priority": request.args.get("priority", ""),
    }
    conditions = []
    params = []

    if filters["course"]:
        conditions.append("course = ?")
        params.append(filters["course"])
    if filters["status"] in STATUSES:
        conditions.append("status = ?")
        params.append(filters["status"])
    if filters["priority"] in PRIORITIES:
        conditions.append("priority = ?")
        params.append(filters["priority"])

    query = "SELECT * FROM tasks"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY due_date ASC, id DESC"

    db = get_db()
    tasks = [with_reminder(task) for task in db.execute(query, params).fetchall()]
    courses = [row["course"] for row in db.execute("SELECT DISTINCT course FROM tasks ORDER BY course").fetchall()]
    row = db.execute(
        "SELECT COUNT(*) AS total, "
        "COALESCE(SUM(CASE WHEN status = '已完成' THEN 1 ELSE 0 END), 0) AS completed "
        "FROM tasks"
    ).fetchone()
    total = row["total"]
    completed = row["completed"]
    completion_rate = f"{completed * 100 / total:.1f}".rstrip("0").rstrip(".") if total else "0"
    stats = {"total": total, "completed": completed, "completion_rate": completion_rate}

    return render_template(
        "tasks/list.html",
        tasks=tasks,
        courses=courses,
        filters=filters,
        stats=stats,
        priorities=PRIORITIES,
        statuses=STATUSES,
    )


@bp.route("/tasks/new", methods=("GET", "POST"))
def create():
    if request.method == "POST":
        data, errors = validate_task(request.form)
        if not errors:
            now = current_timestamp()
            db = get_db()
            cursor = db.execute(
                "INSERT INTO tasks "
                "(name, course, description, due_date, priority, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (*[data[key] for key in ("name", "course", "description", "due_date", "priority", "status")], now, now),
            )
            db.commit()
            flash("任务创建成功。", "success")
            return redirect(url_for("tasks.detail", task_id=cursor.lastrowid))
        return render_template("tasks/form.html", mode="create", task=data, errors=errors), 400

    task = {"name": "", "course": "", "description": "", "due_date": "", "priority": "中", "status": "待完成"}
    return render_template("tasks/form.html", mode="create", task=task, errors={})


@bp.route("/tasks/<int:task_id>")
def detail(task_id):
    return render_template("tasks/detail.html", task=with_reminder(get_task(task_id)), statuses=STATUSES)


@bp.route("/tasks/<int:task_id>/edit", methods=("GET", "POST"))
def edit(task_id):
    task = get_task(task_id)
    if request.method == "POST":
        data, errors = validate_task(request.form)
        if not errors:
            db = get_db()
            db.execute(
                "UPDATE tasks SET name = ?, course = ?, description = ?, due_date = ?, "
                "priority = ?, status = ?, updated_at = ? WHERE id = ?",
                (*[data[key] for key in ("name", "course", "description", "due_date", "priority", "status")],
                 current_timestamp(), task_id),
            )
            db.commit()
            flash("任务修改成功。", "success")
            return redirect(url_for("tasks.detail", task_id=task_id))
        data["id"] = task_id
        return render_template("tasks/form.html", mode="edit", task=data, errors=errors), 400

    return render_template("tasks/form.html", mode="edit", task=task, errors={})


@bp.route("/tasks/<int:task_id>/status", methods=("POST",))
def update_status(task_id):
    task = get_task(task_id)
    status = request.form.get("status", "")
    if status not in STATUSES:
        flash("请选择有效的任务状态。", "error")
        return render_template("tasks/detail.html", task=with_reminder(task), statuses=STATUSES), 400

    db = get_db()
    db.execute("UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?", (status, current_timestamp(), task_id))
    db.commit()
    flash("任务状态已更新。", "success")
    return redirect(url_for("tasks.detail", task_id=task_id))


@bp.route("/tasks/<int:task_id>/delete", methods=("GET", "POST"))
def delete(task_id):
    task = get_task(task_id)
    if request.method == "GET":
        return render_template("tasks/delete.html", task=task)

    action = request.form.get("action")
    if action == "cancel":
        flash("已取消删除，任务保持不变。", "info")
        return redirect(url_for("tasks.detail", task_id=task_id))
    if action != "confirm":
        return render_template("tasks/delete.html", task=task), 400

    db = get_db()
    db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    db.commit()
    flash("任务已删除。", "success")
    return redirect(url_for("tasks.index"))


@bp.app_errorhandler(404)
def not_found(error):
    return render_template("error.html"), 404
