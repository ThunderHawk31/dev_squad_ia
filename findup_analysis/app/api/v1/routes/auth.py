"""
Routes d'authentification pour FindUP
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.core.security import create_access_token, verify_password, get_password_hash
from app.db.database import get_db
from app.models.user import User, UserCreate, UserLogin, Token
from app.services.auth_service import AuthService

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@router.post("/register", response_model=dict)
async def register(user: UserCreate, db: Session = Depends(get_db)):
    """
    Inscription d'un nouvel utilisateur
    """
    # Vérifier si l'utilisateur existe déjà
    existing_user = db.query(User).filter(User.email == user.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Créer le nouvel utilisateur
    hashed_password = get_password_hash(user.password)
    db_user = User(
        email=user.email,
        username=user.username,
        hashed_password=hashed_password,
        full_name=user.full_name
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    return {"message": "User created successfully", "user_id": db_user.id}

@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """
    Connexion utilisateur avec email/password
    """
    user = db.query(User).filter(User.email == form_data.username).first()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/logout")
async def logout():
    """
    Déconnexion utilisateur
    """
    return {"message": "Successfully logged out"}

@router.get("/me")
async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """
    Récupérer les informations de l'utilisateur connecté
    """
    auth_service = AuthService(db)
    user = await auth_service.get_current_user(token)
    return user

@router.post("/refresh-token", response_model=Token)
async def refresh_token(token: str = Depends(oauth2_scheme)):
    """
    Rafraîchir le token d'accès
    """
    # Logique de rafraîchissement du token
    new_token = create_access_token(data={"sub": "user_email"})
    return {"access_token": new_token, "token_type": "bearer"}

@router.post("/forgot-password")
async def forgot_password(email: str, db: Session = Depends(get_db)):
    """
    Demande de réinitialisation de mot de passe
    """
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Logique d'envoi d'email de réinitialisation
    return {"message": "Password reset email sent"}

@router.post("/reset-password")
async def reset_password(token: str, new_password: str, db: Session = Depends(get_db)):
    """
    Réinitialisation du mot de passe avec token
    """
    # Logique de vérification du token et mise à jour du mot de passe
    return {"message": "Password reset successfully"}