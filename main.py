from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.session import AsyncSessionLocal # Або ваш спосіб отримання сесії
from app.db.init_db import init_db

from app.api.v1.endpoints import (auth, consent, patients, records, regions, self_assessment, user)

app = FastAPI(
    title="ЗЗК Реєстр API",
    version="1.0.0",
    description="API для реєстру запальних захворювань кишківника (ВК / ХК)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # в продакшені вказати конкретні origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PREFIX = "/api/v1"

app.include_router(auth.router,              prefix=PREFIX)
app.include_router(user.router,             prefix=PREFIX)
app.include_router(patients.router,          prefix=PREFIX)
app.include_router(records.router,           prefix=PREFIX)
app.include_router(self_assessment.router,  prefix=PREFIX)
app.include_router(regions.router,           prefix=PREFIX)
app.include_router(consent.router,           prefix=PREFIX)


@app.on_event("startup")
async def startup_event():
    async with AsyncSessionLocal() as db:
        await init_db(db)

@app.get("/health")
async def health():
    return {"status": "ok"}