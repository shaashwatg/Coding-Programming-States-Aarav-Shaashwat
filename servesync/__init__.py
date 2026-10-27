"""
ServeSync — Volunteer Management for Nonprofits.

FBLA Coding & Programming 2026-2027
Topic: "Serving the Community: Nonprofit Volunteer Management"

Package layout (layered architecture — each layer only depends on the
layers listed below it):

    ui/        Presentation layer (PySide6 views)          -> services, models
    services/  Business rules & use cases                  -> data, models, core
    data/      SQLite persistence (repositories, schema)   -> models, core
    models/    Domain entities (self-validating dataclasses) -> core
    core/      Cross-cutting utilities (errors, validators, security)
"""

__app_name__ = "ServeSync"
__version__ = "1.1.0"
__all__ = ["__app_name__", "__version__"]
