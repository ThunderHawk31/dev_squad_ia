"""
Routes de gestion des utilisateurs pour FindUP
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.db.database import get_db
from app.models.user import User, UserResponse, UserUpdate, UserProfile
from app.services.user_service import UserService
from app.core.security import get_current_user

router = APIRouter()

@router.get("/", response_model=List[UserResponse])
async def get_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer la liste des utilisateurs avec pagination et recherche
    """
    user_service = UserService(db)
    users = await user_service.get_users(skip=skip, limit=limit, search=search)
    return users

@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer un utilisateur par son ID
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user

@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_update: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Mettre à jour les informations d'un utilisateur
    """
    # Vérifier que l'utilisateur peut modifier ce profil
    if current_user.id != user_id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Mettre à jour les champs
    for field, value in user_update.dict(exclude_unset=True).items():
        setattr(user, field, value)
    
    db.commit()
    db.refresh(user)
    return user

@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Supprimer un utilisateur
    """
    # Seuls les admins peuvent supprimer des utilisateurs
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    db.delete(user)
    db.commit()
    return {"message": "User deleted successfully"}

@router.get("/{user_id}/profile", response_model=UserProfile)
async def get_user_profile(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer le profil détaillé d'un utilisateur
    """
    user_service = UserService(db)
    profile = await user_service.get_user_profile(user_id)
    return profile

@router.put("/{user_id}/profile", response_model=UserProfile)
async def update_user_profile(
    user_id: int,
    profile_update: UserProfile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Mettre à jour le profil d'un utilisateur
    """
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only update your own profile"
        )
    
    user_service = UserService(db)
    updated_profile = await user_service.update_user_profile(user_id, profile_update)
    return updated_profile

@router.get("/{user_id}/friends", response_model=List[UserResponse])
async def get_user_friends(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Récupérer la liste des amis d'un utilisateur
    """
    user_service = UserService(db)
    friends = await user_service.get_user_friends(user_id)
    return friends

@router.post("/{user_id}/friends/{friend_id}")
async def add_friend(
    user_id: int,
    friend_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Ajouter un ami
    """
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only manage your own friends"
        )
    
    user_service = UserService(db)
    result = await user_service.add_friend(user_id, friend_id)
    return result

@router.delete("/{user_id}/friends/{friend_id}")
async def remove_friend(
    user_id: int,
    friend_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Supprimer un ami
    """
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only manage your own friends"
        )
    
    user_service = UserService(db)
    result = await user_service.remove_friend(user_id, friend_id)
    return result