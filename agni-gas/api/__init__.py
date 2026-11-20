from flask import Blueprint, jsonify

api_bp = Blueprint("api", __name__)


@api_bp.errorhandler(ValueError)
def bad_request(err):
    return jsonify({"error": str(err)}), 400


# Each module registers its routes on api_bp. One module per screen group,
# added as we build: dashboard + people now; sales, payments, stock ... next.
from . import dashboard, people  # noqa: E402,F401
