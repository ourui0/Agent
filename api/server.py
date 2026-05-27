"""FastAPI 接口层 — 流式 SSE + 同步模式。"""

import json, logging, uuid
from typing import Any, AsyncGenerator, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from agents.stage2_state import create_initial_state
from agents.stage2_graph import build_graph

logger = logging.getLogger(__name__)
_graph = build_graph()


class PlanRequest(BaseModel):
    query: str = Field(..., description="旅行需求", examples=["2人去北京3天 预算3000"])
    stream: bool = Field(default=True, description="SSE 流式")
    max_revisions: int = Field(default=3, ge=1, le=5)


def _sanitize(state: dict) -> Dict[str, Any]:
    return {"city": state.get("city",""), "budget": state.get("budget",0),
            "days": state.get("days",0), "people": state.get("people",0),
            "itinerary": state.get("itinerary",[]),
            "hotels": [{"name": h.get("name",""), "price_per_night": h.get("price_per_night",0),
                        "rating": h.get("rating",0), "location": h.get("location",""),
                        "reason": h.get("reason","")} for h in state.get("hotels",[])],
            "total_cost": state.get("total_cost",0), "budget_status": state.get("budget_status","unknown"),
            "revision_count": state.get("revision_count",0)}


def create_app() -> FastAPI:
    app = FastAPI(title="旅游规划多智能体系统", version="2.0.0")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/api/v1/plan")
    async def plan(request: PlanRequest):
        if request.stream:
            async def gen():
                config = {"configurable": {"thread_id": str(uuid.uuid4())}}
                init = create_initial_state(request.query, request.max_revisions)
                try:
                    async for chunk in _graph.astream(init, config):
                        for node, update in chunk.items():
                            if node.startswith("__"): continue
                            logs = update.get("logs", [])
                            yield {"event": "agent_update", "data": json.dumps({
                                "agent": node, "log": str(logs[-1]) if logs else "",
                                "partial_state": _sanitize(update)}, ensure_ascii=False)}
                    state = _graph.get_state(config)
                    if state and state.values:
                        yield {"event": "complete", "data": json.dumps(_sanitize(state.values), ensure_ascii=False)}
                except Exception as e:
                    yield {"event": "error", "data": json.dumps({"error": str(e)})}
            return EventSourceResponse(gen())
        else:
            config = {"configurable": {"thread_id": str(uuid.uuid4())}}
            init = create_initial_state(request.query, request.max_revisions)
            async for _ in _graph.astream(init, config): pass
            state = _graph.get_state(config)
            if state and state.values:
                return _sanitize(state.values)
            raise HTTPException(500, "无结果")
    return app

app = create_app()

if __name__ == "__main__":
    import uvicorn; uvicorn.run(app, host="0.0.0.0", port=8000)
