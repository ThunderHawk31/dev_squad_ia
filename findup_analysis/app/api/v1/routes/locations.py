"""
Routes de gestion des localisations pour FindUP (PostGIS)
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.db.database import get_db
from app.models.location import Location, LocationCreate, LocationResponse, LocationUpdate
from app.models.user import User
from app.services.location_service import LocationService
from app.core.security import get_current_user

router = APIRouter()

@router.post("/", response_model=LocationResponse)
async def create_location(
    location: LocationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Créer une nouvelle localisation
    """
    location_service = LocationService(db)
    new_location = await location_service.create_location(location, current_user.id)
    return new_location

@router.get("/", response_model=List[LocationResponse])
async def get_locations(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius: Optional[float] = Query(None, description="Rayon en kilomètres"),
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer les localisations avec filtres géographiques
    """
    location_service = LocationService(db)
    locations = await location_service.get_locations(
        skip=skip, 
        limit=limit,
        latitude=latitude,
        longitude=longitude,
        radius=radius,
        category=category
    )
    return locations

@router.get("/nearby", response_model=List[LocationResponse])
async def get_nearby_locations(
    latitude: float,
    longitude: float,
    radius: float = Query(5.0, description="Rayon en kilomètres"),
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer les localisations à proximité d'un point donné
    """
    location_service = LocationService(db)
    nearby_locations = await location_service.get_nearby_locations(
        latitude=latitude,
        longitude=longitude,
        radius=radius,
        category=category
    )
    return nearby_locations

@router.get("/{location_id}", response_model=LocationResponse)
async def get_location(
    location_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer une localisation par son ID
    """
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location not found"
        )
    return location

@router.put("/{location_id}", response_model=LocationResponse)
async def update_location(
    location_id: int,
    location_update: LocationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Mettre à jour une localisation
    """
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location not found"
        )
    
    # Vérifier que l'utilisateur peut modifier cette localisation
    if location.created_by != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    location_service = LocationService(db)
    updated_location = await location_service.update_location(location_id, location_update)
    return updated_location

@router.delete("/{location_id}")
async def delete_location(
    location_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Supprimer une localisation
    """
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location not found"
        )
    
    # Vérifier que l'utilisateur peut supprimer cette localisation
    if location.created_by != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    db.delete(location)
    db.commit()
    return {"message": "Location deleted successfully"}

@router.get("/search/text")
async def search_locations_by_text(
    query: str = Query(..., min_length=3),
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius: Optional[float] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Recherche textuelle de localisations
    """
    location_service = LocationService(db)
    results = await location_service.search_locations_by_text(
        query=query,
        latitude=latitude,
        longitude=longitude,
        radius=radius
    )
    return results

@router.get("/categories/", response_model=List[str])
async def get_location_categories(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer toutes les catégories de localisations disponibles
    """
    location_service = LocationService(db)
    categories = await location_service.get_categories()
    return categories

@router.post("/{location_id}/favorite")
async def add_location_to_favorites(
    location_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Ajouter une localisation aux favoris
    """
    location_service = LocationService(db)
    result = await location_service.add_to_favorites(location_id, current_user.id)
    return result

@router.delete("/{location_id}/favorite")
async def remove_location_from_favorites(
    location_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Supprimer une localisation des favoris
    """
    location_service = LocationService(db)
    result = await location_service.remove_from_favorites(location_id, current_user.id)
    return result

@router.get("/user/favorites", response_model=List[LocationResponse])
async def get_user_favorite_locations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer les localisations favorites de l'utilisateur
    """
    location_service = LocationService(db)
    favorites = await location_service.get_user_favorites(current_user.id)
    return favorites