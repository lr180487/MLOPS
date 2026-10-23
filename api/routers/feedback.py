"""POST /api/feedback, GET /api/feedback, GET /api/feedback/{id}"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..deps import Ctx
from ..schemas import FeedbackIn

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", status_code=201)
@router.post("/", status_code=201, include_in_schema=False)
async def crear_feedback(fb: FeedbackIn, ctx: Ctx):
    """Registra la etiqueta real de una predicción y actualiza las métricas de producción."""
    try:
        r = await ctx.service.feedback(fb.prediction_id, fb.real, fb.comentario, origen="api")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, **r}


@router.get("")
@router.get("/", include_in_schema=False)
async def listar_feedback(ctx: Ctx, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    return await ctx.service.listar_feedback(limit, offset)


@router.get("/{feedback_id}")
async def obtener_feedback(feedback_id: str, ctx: Ctx):
    r = await ctx.service.obtener_feedback(feedback_id)
    if r is None:
        raise HTTPException(status_code=404, detail="feedback_id no encontrado")
    return r
