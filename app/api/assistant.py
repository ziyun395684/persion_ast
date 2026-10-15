from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.services import hindsight
from app.models import User
from app.services.auth import get_current_user


router = APIRouter()


class AssistantQueryRequest(BaseModel):
    question: str = Field(min_length=1)


def _matching_model_id(question: str, models: list) -> str | None:
    text = question.lower()
    keyword_groups = {
        "project-context": ("项目", "架构", "部署", "代码", "技术", "端口"),
        "user-profile": ("技术栈", "工具", "编程", "开发", "偏好"),
        "work-patterns": ("习惯", "效率", "工作时间", "沟通方式", "作息"),
    }
    available = {
        item.get("id") or item.get("model_id")
        for item in models
        if isinstance(item, dict)
    }
    for model_id, keywords in keyword_groups.items():
        if model_id in available and any(keyword in text for keyword in keywords):
            return model_id
    return None


@router.post("/assistant/query")
async def assistant_query(request: AssistantQueryRequest, user: User = Depends(get_current_user)) -> dict[str, str]:
    if not hindsight.CFG.hindsight_enabled:
        return {
            "answer": "我这边还没有查到相关记忆，等接入记忆后再帮你找找看。",
            "source": "recall",
        }

    models = await hindsight.list_mental_models(user_id=user.id)
    model_id = _matching_model_id(request.question, models)
    if model_id:
        answer = await hindsight.get_mental_model_content(model_id, user_id=user.id)
        if answer:
            return {"answer": answer, "source": "mental_model"}

    answer = await hindsight.reflect(request.question, user_id=user.id)
    if answer:
        return {"answer": answer, "source": "reflect"}

    recalled = await hindsight.recall(request.question, budget="mid", user_id=user.id)
    if recalled:
        return {
            "answer": "\n".join(item["text"] for item in recalled if item.get("text")),
            "source": "recall",
        }
    return {
        "answer": "我这边还没有查到相关记忆，等接入记忆后再帮你找找看。",
        "source": "recall",
    }
