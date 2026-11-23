import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

SECRET_KEY = os.environ["JWT_SECRET"]
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_credentials=True)
