import logging

import requests

from core.config import settings

logger = logging.getLogger(__name__)


def check_face_present(file_bytes: bytes) -> bool:
    """
    Sends image bytes to SightEngine and returns True if at least one face is detected.
    Fails open (returns True) on API errors so uploads aren't blocked when SightEngine is down.
    """
    try:
        response = requests.post(
            "https://api.sightengine.com/1.0/check.json",
            files={"media": ("photo.jpg", file_bytes, "image/jpeg")},
            data={
                "models": "face",
                "api_user": settings.SIGHTENGINE_API_USER,
                "api_secret": settings.SIGHTENGINE_API_SECRET,
            },
            timeout=15,
        )
        result = response.json()

        if result.get("status") != "success":
            logger.warning("SightEngine returned non-success status: %s", result)
            return True

        faces = result.get("faces", [])
        return len(faces) >= 1

    except Exception:
        logger.warning("SightEngine API error, failing open", exc_info=True)
        return True
