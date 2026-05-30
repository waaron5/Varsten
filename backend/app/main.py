from fastapi import FastAPI

from app.api.v1 import api_router

app = FastAPI(title="Varsten", version="0.1.0")
app.include_router(api_router)


@app.get("/health")
def health() -> dict:
    return {"ok": True}
