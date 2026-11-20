import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import imports, planning, reference, schedule, shelf_life

app = FastAPI(title="Планирование производства", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # dev-сервер Vite
    allow_methods=["*"],
    allow_headers=["*"],
)
log = logging.getLogger("app")


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    """Непредвиденная ошибка: полный текст — в лог контейнера, суть — пользователю вместо «Ошибка 500»."""
    log.exception("%s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"Ошибка сервера: {type(exc).__name__}: {exc}"})


app.include_router(imports.router)
app.include_router(reference.router)
app.include_router(planning.router)
app.include_router(schedule.router)
app.include_router(shelf_life.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
