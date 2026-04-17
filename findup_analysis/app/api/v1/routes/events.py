"""
Routes de gestion des événements pour FindUP
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from app.db.database import get_db
from app.models.event import Event, EventCreate, EventResponse, EventUpdate
from app.models.user import User
from app.services.event_service import EventService
from app.core.security import get_current_user

router = APIRouter()

@router.post("/", response_model=EventResponse)
async def create_event(
    event: EventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Créer un nouvel événement
    """
    event_service = EventService(db)
    new_event = await event_service.create_event(event, current_user.id)
    return new_event

@router.get("/", response_model=List[EventResponse])
async def get_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius: Optional[float] = Query(None, description="Rayon en kilomètres"),
    category: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer les événements avec filtres
    """
    event_service = EventService(db)
    events = await event_service.get_events(
        skip=skip,
        limit=limit,
        latitude=latitude,
        longitude=longitude,
        radius=radius,
        category=category,
        start_date=start_date,
        end_date=end_date
    )
    return events

@router.get("/upcoming", response_model=List[EventResponse])
async def get_upcoming_events(
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius: Optional[float] = Query(10.0, description="Rayon en kilomètres"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer les événements à venir
    """
    event_service = EventService(db)
    upcoming_events = await event_service.get_upcoming_events(
        latitude=latitude,
        longitude=longitude,
        radius=radius,
        limit=limit
    )
    return upcoming_events

@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer un événement par son ID
    """
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )
    return event

@router.put("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: int,
    event_update: EventUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Mettre à jour un événement
    """
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )
    
    # Vérifier que l'utilisateur peut modifier cet événement
    if event.created_by != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    event_service = EventService(db)
    updated_event = await event_service.update_event(event_id, event_update)
    return updated_event

@router.delete("/{event_id}")
async def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Supprimer un événement
    """
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )
    
    # Vérifier que l'utilisateur peut supprimer cet événement
    if event.created_by != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    db.delete(event)
    db.commit()
    return {"message": "Event deleted successfully"}

@router.post("/{event_id}/join")
async def join_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Rejoindre un événement
    """
    event_service = EventService(db)
    result = await event_service.join_event(event_id, current_user.id)
    return result

@router.delete("/{event_id}/leave")
async def leave_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Quitter un événement
    """
    event_service = EventService(db)
    result = await event_service.leave_event(event_id, current_user.id)
    return result

@router.get("/{event_id}/participants", response_model=List[dict])
async def get_event_participants(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer la liste des participants à un événement
    """
    event_service = EventService(db)
    participants = await event_service.get_event_participants(event_id)
    return participants

@router.get("/user/created", response_model=List[EventResponse])
async def get_user_created_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer les événements créés par l'utilisateur
    """
    event_service = EventService(db)
    events = await event_service.get_user_created_events(current_user.id)
    return events

@router.get("/user/joined", response_model=List[EventResponse])
async def get_user_joined_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer les événements auxquels l'utilisateur participe
    """
    event_service = EventService(db)
    events = await event_service.get_user_joined_events(current_user.id)
    return events

@router.get("/search/text")
async def search_events_by_text(
    query: str = Query(..., min_length=3),
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius: Optional[float] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Recherche textuelle d'événements
    """
    event_service = EventService(db)
    results = await event_service.search_events_by_text(
        query=query,
        latitude=latitude,
        longitude=longitude,
        radius=radius
    )
    return results