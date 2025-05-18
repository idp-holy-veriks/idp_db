import os
from typing import Dict, Any, Union

import requests
from fastapi import Depends
from fastapi import HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

import models
from database import SessionLocal

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


# Dependency for getting the database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class AuthServiceClient:
    """Client for interacting with the external authentication service"""

    def __init__(self):
        self.base_url = os.getenv("AUTH_SERVICE_URL", "http://idp_auth:8000")

    def login(self, name: str, password: str) -> Dict[str, str]:
        """Forward login request to auth service and return the JWT directly"""
        response = requests.post(
            f"{self.base_url}/login",
            json={"name": name, "password": password}
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Just pass through the token response
        return response.json()

    def register(self, name: str, email: str, password: str) -> Dict[str, Any]:
        """Forward registration to auth service and return the response"""
        response = requests.post(
            f"{self.base_url}/register",
            json={"name": name, "email": email, "password": password}
        )

        if response.status_code != 201:  # Assuming 201 Created is returned
            raise HTTPException(
                status_code=response.status_code,
                detail=response.json().get("detail", "Registration failed")
            )

        # Just return whatever the auth service returned
        return response.json()

    def get_current_user_id(self, token: str = Depends(oauth2_scheme)):
        """
        Verify token with auth service and return the user_id.
        This doesn't interact with the local database.
        """
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

        # Verify the token
        user_id = self.verify_token(token)

        if user_id is None:
            raise credentials_exception

        return user_id

    def get_current_user(self, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
        """
        Get user from local database using user_id from auth service.
        This is only needed if you need the full user object for your business logic.
        """

        # Get the user ID from the auth service
        user_id = self.get_current_user_id(token)

        # Now get the local user record
        user = db.query(models.User).filter(models.User.id == user_id).first()

        if user is None:
            # If the user exists in auth service but not in our database,
            # we can create a minimal record
            user = models.User(
                id=user_id,
                name="User",
                email="user@example.com",
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        return user

    def verify_token(self, token: str) -> Union[int, None]:
        """
        Verify a token with the auth service
        Returns the user_id if valid, None otherwise
        """
        response = requests.post(
            f"{self.base_url}/verify-token",
            headers={"Authorization": f"Bearer {token}"}
        )

        if response.status_code != 200:
            return None

        # Return the user_id from the auth service
        return response.json().get("user_id")
