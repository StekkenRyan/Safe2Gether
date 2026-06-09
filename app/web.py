"""Public-facing web pages: landing, Datenschutz, Impressum."""
from flask import Blueprint, render_template

bp = Blueprint('web', __name__, url_prefix='/')

# Manuell aktualisieren wenn sich der Inhalt der Datenschutzerklärung ändert.
_DATENSCHUTZ_STAND = '09.06.2026'


@bp.get('/')
def index():
    return render_template('index.html')


@bp.get('/datenschutz')
def datenschutz():
    return render_template('datenschutz.html', date=_DATENSCHUTZ_STAND)


@bp.get('/impressum')
def impressum():
    return render_template('impressum.html')
