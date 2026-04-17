# Inventaire complet des endpoints FindUP API

## Structure du projet FindUP

```
findup_analysis/
├── main.py                           # Point d'entrée FastAPI
├── app/
│   ├── api/
│   │   └── v1/
│   │       └── routes/
│   │           ├── auth.py           # Authentification
│   │           ├── users.py          # Gestion utilisateurs
│   │           ├── locations.py      # Gestion localisations (PostGIS)
│   │           ├── events.py         # Gestion événements
│   │           └── notifications.py  # Système notifications (NOUVEAU)
│   ├── models/                       # Modèles Pydantic et SQLAlchemy
│   ├── services/                     # Logique métier
│   ├── core/                         # Configuration et sécurité
│   └── db/                          # Connexion Supabase/PostGIS
└── tests/                           # Tests unitaires
```

## Endpoints existants par module

### 1. Endpoints principaux (main.py)
- `GET /` - Page d'accueil API
- `GET /health` - Vérification santé de l'API

### 2. Authentification (/api/v1/auth)
- `POST /api/v1/auth/register` - Inscription utilisateur
- `POST /api/v1/auth/login` - Connexion utilisateur
- `POST /api/v1/auth/logout` - Déconnexion
- `GET /api/v1/auth/me` - Profil utilisateur connecté
- `POST /api/v1/auth/refresh-token` - Rafraîchissement token
- `POST /api/v1/auth/forgot-password` - Demande réinitialisation mot de passe
- `POST /api/v1/auth/reset-password` - Réinitialisation mot de passe

### 3. Gestion utilisateurs (/api/v1/users)
- `GET /api/v1/users/` - Liste utilisateurs (pagination + recherche)
- `GET /api/v1/users/{user_id}` - Détails utilisateur
- `PUT /api/v1/users/{user_id}` - Mise à jour utilisateur
- `DELETE /api/v1/users/{user_id}` - Suppression utilisateur
- `GET /api/v1/users/{user_id}/profile` - Profil détaillé
- `PUT /api/v1/users/{user_id}/profile` - Mise à jour profil
- `GET /api/v1/users/{user_id}/friends` - Liste amis
- `POST /api/v1/users/{user_id}/friends/{friend_id}` - Ajouter ami
- `DELETE /api/v1/users/{user_id}/friends/{friend_id}` - Supprimer ami

### 4. Gestion localisations (/api/v1/locations) - PostGIS
- `POST /api/v1/locations/` - Créer localisation
- `GET /api/v1/locations/` - Liste localisations (filtres géographiques)
- `GET /api/v1/locations/nearby` - Localisations à proximité
- `GET /api/v1/locations/{location_id}` - Détails localisation
- `PUT /api/v1/locations/{location_id}` - Mise à jour localisation
- `DELETE /api/v1/locations/{location_id}` - Suppression localisation
- `GET /api/v1/locations/search/text` - Recherche textuelle
- `GET /api/v1/locations/categories/` - Catégories disponibles
- `POST /api/v1/locations/{location_id}/favorite` - Ajouter aux favoris
- `DELETE /api/v1/locations/{location_id}/favorite` - Supprimer des favoris
- `GET /api/v1/locations/user/favorites` - Favoris utilisateur

### 5. Gestion événements (/api/v1/events)
- `POST /api/v1/events/` - Créer événement
- `GET /api/v1/events/` - Liste événements (filtres)
- `GET /api/v1/events/upcoming` - Événements à venir
- `GET /api/v1/events/{event_id}` - Détails événement
- `PUT /api/v1/events/{event_id}` - Mise à jour événement
- `DELETE /api/v1/events/{event_id}` - Suppression événement
- `POST /api/v1/events/{event_id}/join` - Rejoindre événement
- `DELETE /api/v1/events/{event_id}/leave` - Quitter événement
- `GET /api/v1/events/{event_id}/participants` - Participants événement
- `GET /api/v1/events/user/created` - Événements créés par utilisateur
- `GET /api/v1/events/user/joined` - Événements rejoints par utilisateur
- `GET /api/v1/events/search/text` - Recherche textuelle événements

### 6. Système notifications (/api/v1/notifications) - NOUVEAU ENDPOINT
- `GET /api/v1/notifications/` - Notifications utilisateur
- `GET /api/v1/notifications/unread/count` - Nombre notifications non lues
- `POST /api/v1/notifications/` - Créer notification (admin)
- `PUT /api/v1/notifications/{notification_id}/read` - Marquer comme lue
- `PUT /api/v1/notifications/read-all` - Marquer toutes comme lues
- `DELETE /api/v1/notifications/{notification_id}` - Supprimer notification
- `GET /api/v1/notifications/types` - Types de notifications
- `POST /api/v1/notifications/preferences` - Préférences notifications
- `GET /api/v1/notifications/preferences` - Récupérer préférences
- `POST /api/v1/notifications/send-bulk` - Notification groupée (admin)
- `POST /api/v1/notifications/location-based` - Notification géolocalisée
- `GET /api/v1/notifications/recent` - Notifications récentes

## Fonctionnalités spécifiques FindUP

### Géolocalisation (PostGIS)
- Recherche par proximité géographique
- Calcul de distances
- Filtrage par rayon
- Recherche géospatiale avancée

### Système social
- Gestion d'amis
- Participation à des événements
- Favoris et préférences
- Notifications en temps réel

### Sécurité
- Authentification JWT
- Gestion des permissions
- Validation des données
- Protection CORS

## Total des endpoints : 47 endpoints

### Répartition par module :
- **Authentification** : 7 endpoints
- **Utilisateurs** : 9 endpoints  
- **Localisations** : 11 endpoints
- **Événements** : 12 endpoints
- **Notifications** : 12 endpoints (NOUVEAU)
- **Système** : 2 endpoints

## Endpoint manquant identifié et implémenté

**Système de notifications en temps réel** - Module complet ajouté avec 12 endpoints pour gérer les notifications push, les préférences utilisateur, et les notifications basées sur la géolocalisation, essentiel pour une plateforme comme FindUP.