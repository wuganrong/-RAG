from flask import Blueprint

from __009__flask.api.v1.conversation import conversation_bp
from __009__flask.api.v1.document import document_bp
from __009__flask.api.v1.kb import kb_bp

v1_bp = Blueprint("v1", __name__, url_prefix="/v1")
v1_bp.register_blueprint(kb_bp)
v1_bp.register_blueprint(document_bp)
v1_bp.register_blueprint(conversation_bp)
