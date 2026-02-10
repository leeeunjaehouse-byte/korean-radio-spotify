#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Spotify OAuth authentication blueprint.
"""

from flask import Blueprint, redirect, url_for, session, request, current_app
from functools import wraps
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from app.models import db, User
import logging

log = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

SPOTIFY_SCOPES = 'playlist-modify-public playlist-modify-private user-read-email'


def get_spotify_oauth():
    """Create and return a SpotifyOAuth instance"""
    return SpotifyOAuth(
        client_id=current_app.config.get('SPOTIFY_CLIENT_ID'),
        client_secret=current_app.config.get('SPOTIFY_CLIENT_SECRET'),
        redirect_uri=current_app.config.get('SPOTIFY_REDIRECT_URI'),
        scope=SPOTIFY_SCOPES
    )


def login_required(f):
    """Decorator to require user login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.spotify'))
        return f(*args, **kwargs)
    return decorated_function


@auth_bp.route('/spotify')
def spotify():
    """Generate Spotify auth URL, redirect to Spotify"""
    sp_oauth = get_spotify_oauth()
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)


@auth_bp.route('/callback')
def callback():
    """Handle Spotify OAuth callback, exchange code for tokens"""
    sp_oauth = get_spotify_oauth()
    code = request.args.get('code')
    error = request.args.get('error')

    if error:
        log.warning(f"Spotify auth error: {error}")
        return redirect(url_for('main.index'))

    if not code:
        log.warning("No authorization code received from Spotify")
        return redirect(url_for('main.index'))

    try:
        token_info = sp_oauth.get_access_token(code)

        if not token_info:
            log.error("Failed to get access token from Spotify")
            return redirect(url_for('auth.spotify'))

        sp = spotipy.Spotify(auth=token_info['access_token'])
        spotify_user = sp.current_user()

        spotify_user_id = spotify_user['id']
        display_name = spotify_user.get('display_name', '')
        email = spotify_user.get('email', '')
        profile_image_url = ''
        if spotify_user.get('images') and len(spotify_user['images']) > 0:
            profile_image_url = spotify_user['images'][0]['url']

        # Create or update user in database
        user = User.query.filter_by(spotify_user_id=spotify_user_id).first()

        if user:
            user.display_name = display_name
            user.email = email
            user.profile_image_url = profile_image_url
            user.is_active = True
            user.set_access_token(token_info['access_token'])
            if 'refresh_token' in token_info:
                user.set_refresh_token(token_info['refresh_token'])
            if 'expires_at' in token_info:
                from datetime import datetime
                user.token_expires_at = datetime.fromtimestamp(token_info['expires_at'])
        else:
            user = User(
                spotify_user_id=spotify_user_id,
                display_name=display_name,
                email=email,
                profile_image_url=profile_image_url,
                is_active=True
            )
            # Set tokens before adding to session (encrypted_access_token is NOT NULL)
            user.set_access_token(token_info['access_token'])
            if 'refresh_token' in token_info:
                user.set_refresh_token(token_info['refresh_token'])
            if 'expires_at' in token_info:
                from datetime import datetime
                user.token_expires_at = datetime.fromtimestamp(token_info['expires_at'])
            db.session.add(user)

        db.session.commit()

        # Set session
        session['user_id'] = user.id
        session.permanent = True

        log.info(f"User logged in: {spotify_user_id}")
        return redirect(url_for('main.dashboard'))

    except Exception as e:
        log.error(f"Error during Spotify callback: {e}")
        return redirect(url_for('main.index'))


@auth_bp.route('/logout')
def logout():
    """Clear session and logout user"""
    user_id = session.get('user_id')
    if user_id:
        log.info(f"User {user_id} logged out")
    session.clear()
    return redirect(url_for('main.index'))
