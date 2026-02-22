from __future__ import annotations


class ListRolesHandler:
    def handle(self) -> tuple[str, ...]:
        return ("admin", "operator", "viewer")
