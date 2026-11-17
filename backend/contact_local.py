"""Loopback-only contact test entry point; no database or application workers."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contact_api import router
from contact_mail import Config
from contact_diagnostics import enable_local

enable_local()

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:5173'],
    allow_credentials=False,
    allow_methods=['POST'],
    allow_headers=['Content-Type'],
    expose_headers=['Retry-After'],
)


@app.get('/health')
def health():
    # Presence/format only: never connect to SMTP or Siteverify.
    return {'service': 'contact-local', 'configured': Config.load() is not None}
