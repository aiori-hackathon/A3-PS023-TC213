import os
import secrets
from fastapi import Header, HTTPException, status

WORKER_SHARED_SECRET = os.getenv("WORKER_SHARED_SECRET", "default-worker-secret")

def verify_worker_token(x_worker_token: str = Header(default="")):
    """Validates shared controller-to-worker token using constant-time comparison."""
    if not secrets.compare_digest(x_worker_token, WORKER_SHARED_SECRET):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: invalid or missing X-Worker-Token header."
        )
    return x_worker_token