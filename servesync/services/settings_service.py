"""
Organization settings and personal comfort preferences.

Comfort settings (theme, text size, motion, spacing, layout, message timing)
are open to *every* signed-in user — nobody should need an administrator's
permission to make the screen usable — and they follow the person's account
from computer to computer. Organization details (name, mission, value of a
volunteer hour) are admin-only.
"""

from __future__ import annotations

from servesync.models import Appearance, MessageDuration, Theme
from servesync.services.base import Service
from servesync.services.session import Permission, Session


class SettingsService(Service):
    # Readable before sign-in (the sign-in screen shows the name and uses the theme).

    def organization_name(self) -> str:
        return self._store.settings.organization_name()

    def appearance(self, session: Session | None = None) -> Appearance:
        """
        A person's comfort settings, or — before anyone signs in — the settings
        last used on this computer. Settings the person never chose fall back
        to the computer's, so a first sign-in keeps the screen as it was.
        """
        device = self._store.settings.device_appearance()
        if session is None or not self._store.accounts.exists(session.account_id):
            return device
        return Appearance.from_settings(self._store.preferences.get_all(session.account_id), device)

    def volunteer_hour_value(self) -> float:
        return self._store.settings.volunteer_hour_value()

    def mission_statement(self) -> str:
        return self._store.settings.mission_statement()

    def set_appearance(
        self,
        session: Session,
        *,
        theme: Theme | None = None,
        font_scale: float | None = None,
        reduce_motion: bool | None = None,
        text_spacing: bool | None = None,
        simplified: bool | None = None,
        message_duration: MessageDuration | None = None,
    ) -> Appearance:
        """
        Change any of the signed-in person's comfort settings (others stay as they are).

        Saved to their account and remembered as this computer's default, in
        one transaction. Invalid values raise ``ValidationError`` and change nothing.
        """
        current = self.appearance(session)
        updated = Appearance(  # validates every value
            theme=current.theme if theme is None else theme,
            font_scale=current.font_scale if font_scale is None else font_scale,
            reduce_motion=current.reduce_motion if reduce_motion is None else reduce_motion,
            text_spacing=current.text_spacing if text_spacing is None else text_spacing,
            simplified=current.simplified if simplified is None else simplified,
            message_duration=current.message_duration if message_duration is None else message_duration,
        )
        with self._store.transaction():
            # Maintenance scripts run with a session that has no stored account;
            # their choices apply to this computer only.
            if self._store.accounts.exists(session.account_id):
                self._store.preferences.set_many(session.account_id, updated.to_settings())
            self._store.settings.set_device_appearance(updated)
        return updated

    def update_organization(self, session: Session, *, name: str, hour_value: object, mission: str = "") -> None:
        """Change the organization's name, mission, and the dollar value of an hour (admins, all-or-nothing)."""
        session.require(Permission.MANAGE_SETTINGS)
        with self._store.transaction():
            self._store.settings.set_organization_name(name)
            self._store.settings.set_volunteer_hour_value(hour_value)
            self._store.settings.set_mission_statement(mission)
