"""
FindUP - FastAPI Application
Plateforme de géolocalisation avec Supabase et PostGIS
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.routes import auth, users, locations, events
from app.core.config import settings

app = FastAPI(
    title="FindUP API",
    description="API pour la plateforme de géolocalisation FindUP",
    version="1.0.0"
)

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_HOSTS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclusion des routes
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(locations.router, prefix="/api/v1/locations", tags=["Locations"])
app.include_router(events.router, prefix="/api/v1/events", tags=["Events"])

@app.get("/")
async def root():
    return {"message": "FindUP API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "FindUP API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)