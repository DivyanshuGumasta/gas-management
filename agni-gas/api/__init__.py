from flask import Blueprint, jsonify

from .util import ApiError

api_bp = Blueprint("api", __name__)


@api_bp.errorhandler(ApiError)
def api_error(err):
    return jsonify({"error": err.message, "field": err.field}), err.status


@api_bp.errorhandler(ValueError)
def bad_request(err):
    return jsonify({"error": str(err)}), 400


# Keep one registered supplier route implementation; people.py was the old picker-only API.
from . import customers, dashboard, payments, suppliers, purchases  # noqa: E402,F401
