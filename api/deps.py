"""FastAPI dependency providers."""

import os

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from auth.utils import ALGORITHM, SECRET_KEY
from object_storage.object_store import ObjectStore, StorageConfigError, build_default_store

_bearer = HTTPBearer(auto_error=False)


def get_object_store() -> ObjectStore:
    """Expose object storage to routes; turns config gaps into HTTP 503 (not Depends 500)."""
    try:
        return build_default_store()
    except StorageConfigError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> int:
    """Resolve user from JWT Bearer token; default user 1 when auth is optional."""
    if credentials and credentials.credentials:
        try:
            payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = payload.get("user_id")
            if user_id is not None:
                return int(user_id)
        except (JWTError, TypeError, ValueError):
            if os.getenv("AUTH_REQUIRED", "").lower() in ("1", "true", "yes"):
                raise HTTPException(status_code=401, detail="Invalid or expired token") from None

    if os.getenv("AUTH_REQUIRED", "").lower() in ("1", "true", "yes"):
        raise HTTPException(status_code=401, detail="Authentication required")
    return 1
