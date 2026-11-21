from flask import Blueprint, jsonify

from .util import ApiError

api_bp = Blueprint("api", __name__)


@api_bp.errorhandler(ApiError)
def api_error(err):
    return jsonify({"error": err.message, "field": err.field}), err.status


@api_bp.errorhandler(ValueError)
def bad_request(err):
    return jsonify({"error": str(err)}), 400


# One module per screen group; sales, stock, purchases ... are added as we build.
from . import customers, dashboard, payments, people  # noqa: E402,F401
