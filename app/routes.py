from flask import Blueprint, jsonify

bp = Blueprint('api', __name__, url_prefix='/api/v1')


@bp.get('/health')
def health():
    return jsonify({'status': 'ok', 'version': '1.0.0'})
