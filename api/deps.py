"""FastAPI dependency providers."""

import os
from functools import lru_cache

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from auth.cookies import ACCESS_COOKIE
from auth.token_service import decode_access_token
from auth.utils import ALGORITHM, SECRET_KEY
from object_storage.object_store import ObjectStore, StorageConfigError, build_default_store

_bearer = HTTPBearer(auto_error=False)
_AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "true").lower() in ("1", "true", "yes")
_ALLOW_LEGACY_ANON = os.getenv("ALLOW_LEGACY_ANON_USER", "false").lower() in ("1", "true", "yes")


@lru_cache(maxsize=1)
def _cached_object_store() -> ObjectStore:
    return build_default_store()


def get_object_store() -> ObjectStore:
    """Expose object storage to routes; turns config gaps into HTTP 503 (not Depends 500)."""
    try:
        return _cached_object_store()
    except StorageConfigError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


def _token_from_request(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if credentials and credentials.credentials:
        return credentials.credentials
    cookie = request.cookies.get(ACCESS_COOKIE)
    if cookie:
        return cookie
    return None


def get_current_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> int:
    """Resolve user from access cookie or Bearer token."""
    token = _token_from_request(request, credentials)
    if token:
        uid = decode_access_token(token)
        if uid is not None:
            return uid
        if _AUTH_REQUIRED:
            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
                legacy_uid = payload.get("user_id")
                if legacy_uid is not None:
                    return int(legacy_uid)
            except (JWTError, TypeError, ValueError):
                pass
            raise HTTPException(status_code=401, detail="Invalid or expired token")

    if _AUTH_REQUIRED:
        raise HTTPException(status_code=401, detail="Authentication required")

    if _ALLOW_LEGACY_ANON:
        return 1
    raise HTTPException(status_code=401, detail="Authentication required")
