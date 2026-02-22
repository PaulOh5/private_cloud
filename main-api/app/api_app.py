from app.bootstrap.app_factory import create_api_app

app = create_api_app(include_workers=False)
