from flask import Blueprint

download_bp = Blueprint('download', __name__)

# Import routes to register them with the blueprint
from . import user, initiate, serve, admin, statistics, play
