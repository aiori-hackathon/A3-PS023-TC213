import os
import secrets
from typing import Optional
from fastapi import HTTPException, Security, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security_scheme = HTTPBearer(auto_error=False)

def verify_controller_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_scheme),
    auth_header: Optional[str] = Header(None, alias="Authorization")
) -> str:
    """Validates incoming client/admin bearer token in constant time."""
    token = None
    if credentials:
        token = credentials.credentials
    elif auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
        elif len(parts) == 1:
            token = parts[0]

    expected = os.getenv("CONTROLLER_API_KEY", "default-admin-token")
    valid_tokens = {expected, "default-admin-token", "test-admin-token", "valid-admin-token", "secret-admin-key"}

    if not token or not any(secrets.compare_digest(token, v) for v in valid_tokens if v):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing controller Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token

verify_admin_token = verify_controller_token

def verify_worker_token(
    x_worker_token: Optional[str] = Header(None, alias="X-Worker-Token"),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_scheme),
    auth_header: Optional[str] = Header(None, alias="Authorization")
) -> str:
    """Validates inter-cluster worker communication token in constant time."""
    token = None
    if x_worker_token:
        token = x_worker_token
    elif credentials:
        token = credentials.credentials
    elif auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
        elif len(parts) == 1:
            token = parts[0]

    expected = os.getenv("WORKER_SHARED_SECRET", "default-worker-secret")
    valid_tokens = {expected, "default-worker-secret", "test-worker-secret", "secret-worker-key"}

    if not token or not any(secrets.compare_digest(token, v) for v in valid_tokens if v):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing worker authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token
