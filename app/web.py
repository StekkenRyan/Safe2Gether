"""Public-facing web pages: landing, Datenschutz, Impressum."""
from datetime import date

from flask import Blueprint, render_template

bp = Blueprint('web', __name__, url_prefix='/')


@bp.get('/')
def index():
    return render_template('index.html')


@bp.get('/datenschutz')
def datenschutz():
    return render_template('datenschutz.html', date=date.today().strftime('%d.%m.%Y'))


@bp.get('/impressum')
def impressum():
    return render_template('impressum.html')
