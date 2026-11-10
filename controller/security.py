import os
import secrets
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

CONTROLLER_API_KEY = os.getenv("CONTROLLER_API_KEY", "default-admin-token")
WORKER_SHARED_SECRET = os.getenv("WORKER_SHARED_SECRET", "default-worker-secret")

security_scheme = HTTPBearer(auto_error=False)

def verify_controller_token(credentials: HTTPAuthorizationCredentials = Security(security_scheme)):
    """Validates incoming client bearer token in constant time."""
    if not credentials or not secrets.compare_digest(credentials.credentials, CONTROLLER_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing controller Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials