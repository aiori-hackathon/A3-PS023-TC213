import subprocess
import logging
import os
from pathlib import Path

logger = logging.getLogger("worker_storage")

def create_cow_overlay(base_image_path: str, overlay_path: str) -> bool:
    """
    Creates a thin Copy-on-Write QCOW2 overlay pointing to base_image_path as backing file.
    """
    try:
        if os.path.exists(overlay_path):
            os.remove(overlay_path)
            
        cmd = [
            "qemu-img", "create",
            "-f", "qcow2",
            "-b", os.path.abspath(base_image_path),
            "-F", "qcow2",
            overlay_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info(f"Created CoW overlay {overlay_path} linked to {base_image_path}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.warning(f"Failed to create CoW overlay via qemu-img: {e}. Fallback required.")
        return False

def remove_cow_overlay(overlay_path: str):
    """Safely cleans up an overlay disk image."""
    try:
        if overlay_path and os.path.exists(overlay_path):
            os.remove(overlay_path)
            logger.info(f"Removed CoW overlay disk {overlay_path}")
    except OSError as e:
        logger.error(f"Error removing disk {overlay_path}: {e}")
