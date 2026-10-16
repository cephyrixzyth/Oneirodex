from flask import Blueprint

games_bp = Blueprint('games', __name__)

# Import routes to register them with the blueprint
from . import add, details, edit
