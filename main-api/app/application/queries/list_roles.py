from __future__ import annotations


class ListRolesHandler:
    async def handle(self) -> tuple[str, ...]:
        return ("admin", "operator", "viewer")
