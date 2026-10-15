from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TodoItem


TODO_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "todo_add",
            "description": "新增一条待办事项",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "待办内容"},
                    "due_date": {
                        "type": "string",
                        "description": "截止日期，格式 YYYY-MM-DD",
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "todo_list",
            "description": "查询待办事项",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["open", "done"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "todo_done",
            "description": "将一条待办标记为已完成",
            "parameters": {
                "type": "object",
                "properties": {"todo_id": {"type": "integer"}},
                "required": ["todo_id"],
            },
        },
    },
]


def _success(data):
    return {"ok": True, "data": data, "error": None}


def _error(message: str):
    return {"ok": False, "data": None, "error": message}


def _parse_due_date(value: date | str | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise ValueError("due_date must use YYYY-MM-DD format") from None
    raise ValueError("due_date must be a date or YYYY-MM-DD string")


def _serialize(item: TodoItem) -> dict:
    return {
        "id": item.id,
        "content": item.content,
        "status": item.status,
        "due_date": item.due_date.isoformat() if item.due_date else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


async def _todo_add_impl(
    db: Session, content: str, due_date: date | str | None = None, user_id: int = 1
) -> dict:
    content = content.strip() if isinstance(content, str) else ""
    if not content:
        return _error("content cannot be empty")
    if len(content) > 200:
        return _error("content must be at most 200 characters")
    try:
        parsed_due_date = _parse_due_date(due_date)
    except ValueError as exc:
        return _error(str(exc))

    item = TodoItem(user_id=user_id, content=content, due_date=parsed_due_date)
    try:
        db.add(item)
        db.commit()
        db.refresh(item)
    except Exception:
        db.rollback()
        return _error("failed to save todo")
    return _success(_serialize(item))


async def _todo_list_impl(db: Session, status: str | None = None, user_id: int = 1) -> dict:
    if status not in (None, "open", "done"):
        return _error("status must be open or done")
    statement = select(TodoItem).where(TodoItem.user_id == user_id).order_by(TodoItem.id.asc())
    if status is not None:
        statement = statement.where(TodoItem.status == status)
    items = db.scalars(statement).all()
    return _success([_serialize(item) for item in items])


async def _todo_done_impl(db: Session, todo_id: int, user_id: int = 1) -> dict:
    try:
        item_id = int(todo_id)
    except (TypeError, ValueError):
        return _error("todo_id must be an integer")
    item = db.scalar(select(TodoItem).where(TodoItem.id == item_id, TodoItem.user_id == user_id))
    if item is None:
        return _error("todo not found")
    item.status = "done"
    try:
        db.commit()
        db.refresh(item)
    except Exception:
        db.rollback()
        return _error("failed to update todo")
    return _success(_serialize(item))


async def todo_add(db: Session, content: str, due_date: date | str | None = None) -> dict:
    from app.services.graph import todo_graph

    value = due_date.isoformat() if isinstance(due_date, date) else due_date
    result = await todo_graph.ainvoke(
        {"operation": "add", "content": content, "due_date": value},
        context={"db": db},
    )
    return {key: result.get(key) for key in ("ok", "data", "error")}


async def todo_list(db: Session, status: str | None = None) -> dict:
    from app.services.graph import todo_graph

    result = await todo_graph.ainvoke(
        {"operation": "list", "status": status}, context={"db": db}
    )
    return {key: result.get(key) for key in ("ok", "data", "error")}


async def todo_done(db: Session, todo_id: int) -> dict:
    from app.services.graph import todo_graph

    result = await todo_graph.ainvoke(
        {"operation": "done", "todo_id": todo_id}, context={"db": db}
    )
    return {key: result.get(key) for key in ("ok", "data", "error")}
