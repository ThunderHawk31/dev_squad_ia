"""
Routes de gestion des notifications pour FindUP
Endpoint manquant identifié - Système de notifications en temps réel
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from app.db.database import get_db
from app.models.notification import Notification, NotificationCreate, NotificationResponse, NotificationUpdate
from app.models.user import User
from app.services.notification_service import NotificationService
from app.core.security import get_current_user

router = APIRouter()

@router.get("/", response_model=List[NotificationResponse])
async def get_user_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    unread_only: bool = Query(False, description="Afficher seulement les notifications non lues"),
    notification_type: Optional[str] = Query(None, description="Filtrer par type de notification"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer les notifications de l'utilisateur connecté
    """
    notification_service = NotificationService(db)
    notifications = await notification_service.get_user_notifications(
        user_id=current_user.id,
        skip=skip,
        limit=limit,
        unread_only=unread_only,
        notification_type=notification_type
    )
    return notifications

@router.get("/unread/count")
async def get_unread_notifications_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer le nombre de notifications non lues
    """
    notification_service = NotificationService(db)
    count = await notification_service.get_unread_count(current_user.id)
    return {"unread_count": count}

@router.post("/", response_model=NotificationResponse)
async def create_notification(
    notification: NotificationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Créer une nouvelle notification (pour les admins ou notifications système)
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create notifications"
        )
    
    notification_service = NotificationService(db)
    new_notification = await notification_service.create_notification(notification)
    return new_notification

@router.put("/{notification_id}/read")
async def mark_notification_as_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Marquer une notification comme lue
    """
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == current_user.id
    ).first()
    
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
    
    notification.is_read = True
    notification.read_at = datetime.utcnow()
    db.commit()
    
    return {"message": "Notification marked as read"}

@router.put("/read-all")
async def mark_all_notifications_as_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Marquer toutes les notifications comme lues
    """
    notification_service = NotificationService(db)
    result = await notification_service.mark_all_as_read(current_user.id)
    return result

@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Supprimer une notification
    """
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == current_user.id
    ).first()
    
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
    
    db.delete(notification)
    db.commit()
    return {"message": "Notification deleted successfully"}

@router.get("/types")
async def get_notification_types(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer tous les types de notifications disponibles
    """
    notification_service = NotificationService(db)
    types = await notification_service.get_notification_types()
    return {"notification_types": types}

@router.post("/preferences")
async def update_notification_preferences(
    preferences: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Mettre à jour les préférences de notification de l'utilisateur
    """
    notification_service = NotificationService(db)
    result = await notification_service.update_user_preferences(current_user.id, preferences)
    return result

@router.get("/preferences")
async def get_notification_preferences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer les préférences de notification de l'utilisateur
    """
    notification_service = NotificationService(db)
    preferences = await notification_service.get_user_preferences(current_user.id)
    return preferences

@router.post("/send-bulk")
async def send_bulk_notification(
    notification_data: dict,
    user_ids: List[int],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Envoyer une notification à plusieurs utilisateurs (admins seulement)
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can send bulk notifications"
        )
    
    notification_service = NotificationService(db)
    result = await notification_service.send_bulk_notification(notification_data, user_ids)
    return result

@router.post("/location-based")
async def send_location_based_notification(
    notification_data: dict,
    latitude: float,
    longitude: float,
    radius: float = Query(..., description="Rayon en kilomètres"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Envoyer une notification basée sur la géolocalisation
    Utile pour FindUP - notifications d'événements ou lieux à proximité
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can send location-based notifications"
        )
    
    notification_service = NotificationService(db)
    result = await notification_service.send_location_based_notification(
        notification_data, latitude, longitude, radius
    )
    return result

@router.get("/recent")
async def get_recent_notifications(
    hours: int = Query(24, ge=1, le=168, description="Notifications des X dernières heures"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer les notifications récentes
    """
    notification_service = NotificationService(db)
    notifications = await notification_service.get_recent_notifications(current_user.id, hours)
    return notifications