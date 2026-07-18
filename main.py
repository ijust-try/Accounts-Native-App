"""
Entry point for the API. Run it with:

    uvicorn main:app --reload

Then open http://127.0.0.1:8000/docs in a browser to see and test every
endpoint interactively (this page is generated automatically by FastAPI).
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth_routes import router as auth_router
from report_routes import router as report_router

app = FastAPI(title="Hostel Management API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(report_router)


@app.get("/")
def health_check():
    return {"status": "ok"}