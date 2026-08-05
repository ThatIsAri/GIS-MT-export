from app import app
from datamatrix_storage_api import (
    datamatrix_storage_bp,
)
from document_catalog import (
    document_catalog_bp,
)
from entity_api import entity_api
from fine_matrix_api import (
    fine_matrix_bp,
)
from pipeline_ui import pipeline_ui_bp
from violations_api import violations_bp
from dashboard_api import analytics_dashboard_bp


app.register_blueprint(
    entity_api
)

app.register_blueprint(
    pipeline_ui_bp
)

app.register_blueprint(
    document_catalog_bp
)

app.register_blueprint(
    datamatrix_storage_bp
)

app.register_blueprint(
    violations_bp
)

app.register_blueprint(
    fine_matrix_bp
)

app.register_blueprint(
    analytics_dashboard_bp
)