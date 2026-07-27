from app import app
from entity_api import entity_api
from pipeline_ui import pipeline_ui_bp


app.register_blueprint(
    entity_api
)

app.register_blueprint(
    pipeline_ui_bp
)