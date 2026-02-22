from __future__ import annotations

from app.bootstrap.app_factory import create_api_app


def create_app(*, include_workers: bool = False):
    return create_api_app(include_workers=include_workers)


app = create_app(include_workers=False)
