from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import imports, planning, reference

app = FastAPI(title="Планирование производства", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # dev-сервер Vite
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(imports.router)
app.include_router(reference.router)
app.include_router(planning.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
