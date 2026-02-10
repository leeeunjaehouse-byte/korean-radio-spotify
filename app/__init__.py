import logging
from logging.handlers import RotatingFileHandler
import os
from flask import Flask
from flask_migrate import Migrate
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import get_config
from app.models import db


# Radio programs configuration
PROGRAMS = [
    {
        'name': '이상순',
        'station': 'MBC FM4U',
        'source': 'mbc',
        'prog_code': 'FM4U000001364',
        'description': 'MBC FM4U 이상순의 음악도시',
    },
    {
        'name': '윤상',
        'station': 'MBC FM4U',
        'source': 'mbc',
        'prog_code': 'FM4U000001070',
        'description': 'MBC FM4U 배철수의 음악캠프 (윤상 대행)',
    },
    {
        'name': '이현우',
        'station': 'KBS Cool FM',
        'source': 'kbs',
        'prog_code': 'R2007-0069',
        'description': 'KBS Cool FM 이현우의 음악앨범',
    },
    {
        'name': '전기현',
        'station': 'KBS Classic FM',
        'source': 'kbs_board',
        'prog_code': 'R2007-0077',
        'bbs_id': 'R2007-0077-03-821927',
        'description': 'KBS Classic FM 세상의 모든 음악',
    },
]

# Create a global scheduler instance
scheduler = BackgroundScheduler(timezone='Asia/Seoul')


def create_app(config=None):
    """Application factory for creating Flask app instances"""
    app = Flask(__name__)

    # Load configuration
    if config is None:
        config = get_config()
    app.config.from_object(config)

    # Fix DATABASE_URL for PostgreSQL (Render uses postgres:// but SQLAlchemy needs postgresql://)
    db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if db_url.startswith('postgres://'):
        app.config['SQLALCHEMY_DATABASE_URI'] = db_url.replace('postgres://', 'postgresql://', 1)

    # Add PROGRAMS to app config
    app.config['PROGRAMS'] = PROGRAMS

    # Initialize extensions
    db.init_app(app)
    Migrate(app, db)

    # Configure logging
    configure_logging(app)

    # Register blueprints
    register_blueprints(app)

    # Create database tables
    with app.app_context():
        db.create_all()

    # Initialize APScheduler (only in main process, not in reloader)
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        _setup_scheduler(app)

    return app


def _setup_scheduler(app):
    """Setup APScheduler with daily playlist creation job"""
    if scheduler.running:
        return

    from app.jobs import daily_create_playlists

    # Daily job at KST 21:00 (12:00 UTC)
    scheduler.add_job(
        func=daily_create_playlists,
        trigger='cron',
        hour=21,
        minute=0,
        id='daily_create_playlists',
        name='Daily Playlist Creation',
        replace_existing=True,
        args=[app],
    )

    scheduler.start()
    app.logger.info('APScheduler started - daily job scheduled at KST 21:00')


def register_blueprints(app):
    """Register application blueprints"""
    try:
        from app.blueprints.auth import auth_bp
        from app.blueprints.routes import routes_bp
        from app.blueprints.api import api_bp

        app.register_blueprint(auth_bp, url_prefix='/auth')
        app.register_blueprint(routes_bp)
        app.register_blueprint(api_bp, url_prefix='/api')

    except ImportError as e:
        app.logger.warning(f'Some blueprints could not be imported: {e}')


def configure_logging(app):
    """Configure application logging"""
    if not app.debug and not app.testing:
        if not os.path.exists('logs'):
            os.mkdir('logs')

        file_handler = RotatingFileHandler(
            'logs/korean_radio_spotify.log',
            maxBytes=10240000,
            backupCount=10
        )

        formatter = logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)

        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)
        app.logger.info('Korean Radio Spotify application startup')
