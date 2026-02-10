#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main page routes blueprint.

Handles:
- Landing page
- Dashboard
- Admin page
"""

from flask import Blueprint, render_template, session, redirect, url_for, current_app
from app.models import db, User, UserProgram, UserPlaylist
from sqlalchemy import func
from app.blueprints.auth import login_required
import logging
import json

log = logging.getLogger(__name__)

routes_bp = Blueprint('main', __name__)


@routes_bp.route('/')
def index():
    """Landing page - redirect to dashboard if already logged in"""
    if 'user_id' in session:
        return redirect(url_for('main.dashboard'))
    return render_template('index.html')


@routes_bp.route('/dashboard')
@login_required
def dashboard():
    """User dashboard - requires login"""
    user_id = session.get('user_id')

    # Get user from database
    user = User.query.get(user_id)
    if not user:
        session.clear()
        return redirect(url_for('main.index'))

    # Get programs list
    programs = current_app.config.get('PROGRAMS', [])

    # Get user's followed programs
    user_program_codes = db.session.query(UserProgram.program_code).filter_by(
        user_id=user_id
    ).all()
    followed_programs = {up[0] for up in user_program_codes}

    # Get recent playlist history (last 30)
    recent_playlists = UserPlaylist.query.filter_by(user_id=user_id).order_by(
        UserPlaylist.created_date.desc()
    ).limit(30).all()

    # Prepare program data with follow status
    programs_with_status = []
    for program in programs:
        prog_code = program.get('prog_code')
        programs_with_status.append({
            **program,
            'is_followed': prog_code in followed_programs
        })

    return render_template(
        'dashboard.html',
        user=user,
        programs=programs_with_status,
        recent_playlists=recent_playlists
    )


@routes_bp.route('/admin')
@login_required
def admin():
    """Admin page - show cache status and job runs"""
    from app.models import SongCache
    from datetime import datetime, timedelta

    user_id = session.get('user_id')
    user = User.query.get(user_id)

    if not user:
        session.clear()
        return redirect(url_for('main.index'))

    # Get cache statistics
    cache_stats = db.session.query(
        SongCache.program_code,
        func.count(SongCache.id).label('count'),
        func.max(SongCache.fetched_at).label('last_fetched')
    ).group_by(SongCache.program_code).all()

    # Get playlist creation statistics
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    playlist_stats = db.session.query(
        UserPlaylist.program_code,
        func.count(UserPlaylist.id).label('count'),
        func.sum(UserPlaylist.total_songs).label('total_songs'),
        func.sum(UserPlaylist.songs_added).label('songs_added'),
        func.sum(UserPlaylist.songs_not_found).label('songs_not_found')
    ).filter(
        UserPlaylist.created_at >= thirty_days_ago
    ).group_by(UserPlaylist.program_code).all()

    # Get programs list and convert to JSON for frontend
    programs = current_app.config.get('PROGRAMS', [])
    programs_json = json.dumps(programs)

    return render_template(
        'admin.html',
        user=user,
        cache_stats=cache_stats,
        playlist_stats=playlist_stats,
        programs_json=programs_json
    )
