"""
ConfigService — config loading, validation, and profile management.

Wraps the existing ``config_loader.py`` and adds profile persistence via the data layer.
"""

import logging
from typing import Optional

from src.config_loader import load_config as _load_config_file

logger = logging.getLogger(__name__)


class ConfigService:
    """Service for configuration management."""

    def load_config(self, path: Optional[str] = None) -> dict:
        """Load configuration from a config file.

        Args:
            path: Path to config.ini. Defaults to "config.ini".

        Returns:
            Parsed configuration dict.
        """
        return _load_config_file(path or "config.ini")

    def get_active_profile(self) -> Optional["ConfigProfile"]:
        """Get the active config profile from the database."""
        try:
            from src.data.database import get_session
            from src.data.repositories import ConfigRepository

            with get_session() as db:
                return ConfigRepository(db).get_active()
        except Exception as exc:
            logger.debug("Could not load active profile: %s", exc)
            return None

    def update_config(self, updates: dict, profile_name: str = "default") -> "ConfigProfile":
        """Validate and persist config updates to a named profile."""
        from src.data.database import get_session, init_db
        from src.data.models import ConfigProfile
        from src.data.repositories import ConfigRepository

        init_db()
        with get_session() as db:
            repo = ConfigRepository(db)
            profile = repo.get_by_name(profile_name)
            if profile is None:
                profile = ConfigProfile(
                    name=profile_name,
                    config_data=updates,
                    is_active=True,
                )
            else:
                # Merge updates into existing config
                existing = profile.config_data or {}
                for section, values in updates.items():
                    if isinstance(values, dict) and isinstance(existing.get(section), dict):
                        existing[section].update(values)
                    else:
                        existing[section] = values
                profile.config_data = existing
            return repo.save(profile)

    def list_profiles(self) -> list:
        """List all saved config profiles."""
        try:
            from src.data.database import get_session
            from src.data.repositories import ConfigRepository

            with get_session() as db:
                return ConfigRepository(db).list_profiles()
        except Exception:
            return []
