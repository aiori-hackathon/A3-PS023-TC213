import logging
import json
import os
from datetime import datetime, timezone

logger = logging.getLogger("controller_audit")
AUDIT_LOG_FILE = os.getenv("AUDIT_LOG_FILE", "data/audit.log")

os.makedirs(os.path.dirname(AUDIT_LOG_FILE), exist_ok=True)

def audit_log(action: str, detail: str, user: str = "system"):
    """Records security and cluster lifecycle events to structured audit storage."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "detail": detail,
        "user": user
    }
    logger.info(f"AUDIT [{action}] {detail} by {user}")
    try:
        with open(AUDIT_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        logger.error(f"Failed to write audit log: {e}")
