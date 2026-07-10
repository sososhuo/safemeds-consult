import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import create_router
from app.core.config import ALLOWED_ORIGINS
from app.core.logging import configure_logging
from app.data_store import load_knowledge
from app.repositories.consultation_repository import ConsultationRepository
from app.repositories.history_repository import HistoryRepository
from app.services.analysis_service import AnalysisService
from app.services.consultation_service import MedicationConsultationService


configure_logging()
logger = logging.getLogger(__name__)
records = load_knowledge()
history_repository = HistoryRepository()
consultation_repository = ConsultationRepository()
analysis_service = AnalysisService(records=records, history_repository=history_repository)
consultation_service = MedicationConsultationService(records=records, repository=consultation_repository)

app = FastAPI(title="SafeMeds Medication Consultation API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(create_router(records, analysis_service, history_repository, consultation_service, consultation_repository))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_exception path=%s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务内部错误，请稍后重试。"})
