#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Background job for daily playlist creation.

Runs scheduled job to:
- Get all active users
- Find their followed programs
- Fetch songs and create Spotify playlists
- Handle caching to avoid re-scraping
"""

from datetime import datetime, date
from app.models import db, User, UserProgram, UserPlaylist, SongCache
from app import radio_scraper, spotify_client
import spotipy
import logging
import json

log = logging.getLogger(__name__)


def daily_create_playlists(app):
    """
    Daily job to create playlists for all active users.

    Runs within app context. For each active user:
    - Get followed programs
    - Check cache for songs
    - Fetch songs if not cached
    - Search Spotify for tracks
    - Create/update Spotify playlist
    - Log results
    """
    with app.app_context():
        log.info("Starting daily playlist creation job")

        try:
            # Get all active users
            active_users = User.query.filter_by(is_active=True).all()

            if not active_users:
                log.info("No active users found")
                return

            log.info(f"Processing {len(active_users)} active users")

            # Get programs config
            from flask import current_app
            programs = current_app.config.get('PROGRAMS', [])
            program_map = {p.get('prog_code'): p for p in programs}

            successful_playlists = 0
            failed_playlists = 0

            # Process each user
            for user in active_users:
                try:
                    user_successful, user_failed = _process_user_playlists(
                        user, program_map, app
                    )
                    successful_playlists += user_successful
                    failed_playlists += user_failed
                except Exception as e:
                    log.error(f"Error processing user {user.id}: {e}")
                    failed_playlists += 1

            log.info(f"Daily playlist job completed: {successful_playlists} successful, "
                    f"{failed_playlists} failed")

        except Exception as e:
            log.error(f"Fatal error in daily_create_playlists: {e}")


def _process_user_playlists(user, program_map, app):
    """
    Process all playlists for a single user.

    Args:
        user (User): User object
        program_map (dict): Map of program_code to program config
        app: Flask app instance

    Returns:
        tuple: (successful_count, failed_count)
    """
    user_id = user.id
    successful_count = 0
    failed_count = 0

    try:
        # Get user's followed programs
        user_programs = UserProgram.query.filter_by(user_id=user_id).all()

        if not user_programs:
            log.debug(f"User {user_id} has no followed programs")
            return 0, 0

        log.info(f"User {user_id} has {len(user_programs)} followed programs")

        # Create Spotify client for user once
        try:
            sp = _get_user_spotify_client(user)
        except Exception as e:
            log.error(f"Cannot create Spotify client for user {user_id}: {e}")
            return 0, len(user_programs)

        # Process each program
        for user_program in user_programs:
            program_code = user_program.program_code
            program = program_map.get(program_code)

            if not program:
                log.warning(f"Program {program_code} not found in config")
                failed_count += 1
                continue

            try:
                success = _create_playlist_for_program(user, program, sp)
                if success:
                    successful_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                log.error(f"Error creating playlist for user {user_id}, "
                         f"program {program_code}: {e}")
                failed_count += 1

        return successful_count, failed_count

    except Exception as e:
        log.error(f"Error processing user {user_id}: {e}")
        return 0, 1


def _create_playlist_for_program(user, program, sp):
    """
    Create playlist for a single program for a user.

    Args:
        user (User): User object
        program (dict): Program config
        sp: Spotify client

    Returns:
        bool: True if successful, False otherwise
    """
    program_code = program.get('prog_code')
    today = date.today()

    # Check if playlist already exists for today
    existing = UserPlaylist.query.filter_by(
        user_id=user.id,
        program_code=program_code,
        created_date=today
    ).first()

    if existing:
        log.debug(f"Playlist already exists for user {user.id}, "
                 f"program {program_code} on {today}")
        return True

    # Fetch or get cached songs
    songs = _fetch_or_cache_songs(program, today)

    if not songs:
        log.warning(f"No songs found for program {program_code} on {today}")
        return False

    log.info(f"Processing {len(songs)} songs for program {program_code}")

    try:
        # Get playlist name
        playlist_name = spotify_client.get_playlist_name(program, datetime.now())

        # Find or create playlist
        playlist_id, is_new = spotify_client.find_or_create_playlist(sp, playlist_name)

        # Search for songs and collect track IDs
        track_ids = []
        not_found_count = 0

        for song in songs:
            try:
                track_id = spotify_client.search_spotify_track(
                    sp,
                    song.get('title'),
                    song.get('artist')
                )

                if track_id:
                    track_ids.append(track_id)
                else:
                    not_found_count += 1
            except Exception as e:
                log.debug(f"Error searching for track: {e}")
                not_found_count += 1

        # Add tracks to playlist
        added_count = 0
        if track_ids:
            try:
                sp.playlist_add_items(playlist_id, track_ids)
                added_count = len(track_ids)
                log.debug(f"Added {added_count} tracks to playlist {playlist_id}")
            except Exception as e:
                log.error(f"Error adding tracks to playlist: {e}")
                added_count = len(track_ids)

        # Get playlist URL
        try:
            playlist_info = sp.playlist(playlist_id)
            playlist_url = playlist_info.get('external_urls', {}).get('spotify', '')
        except Exception as e:
            log.warning(f"Could not get playlist info: {e}")
            playlist_url = f"https://open.spotify.com/playlist/{playlist_id}"

        # Save playlist to database
        user_playlist = UserPlaylist(
            user_id=user.id,
            program_code=program_code,
            created_date=today,
            spotify_playlist_id=playlist_id,
            spotify_playlist_url=playlist_url,
            playlist_name=playlist_name,
            total_songs=len(songs),
            songs_added=added_count,
            songs_not_found=not_found_count
        )

        db.session.add(user_playlist)
        db.session.commit()

        log.info(f"Created playlist for user {user.id}, program {program_code}: "
                f"{added_count}/{len(songs)} songs added ({not_found_count} not found)")

        return True

    except Exception as e:
        log.error(f"Error creating playlist for program {program_code}: {e}")
        return False


def _fetch_or_cache_songs(program, target_date):
    """
    Fetch songs from cache or scrape and cache them.

    Args:
        program (dict): Program config
        target_date (date): Target date for songs

    Returns:
        list: List of songs with 'title' and 'artist' keys, or None
    """
    program_code = program.get('prog_code')

    # Check cache first
    try:
        cache = SongCache.query.filter_by(
            program_code=program_code,
            cache_date=target_date
        ).first()

        if cache:
            try:
                songs = json.loads(cache.songs_json)
                log.debug(f"Using cached songs for {program_code} on {target_date}")
                return songs
            except json.JSONDecodeError:
                log.warning(f"Failed to parse cached songs for {program_code}")
    except Exception as e:
        log.debug(f"Error reading cache: {e}")

    # Fetch from scraper
    try:
        log.debug(f"Fetching songs for {program_code} from radio source")
        songs = radio_scraper.fetch_songs(program)

        if songs:
            # Cache the songs
            try:
                existing_cache = SongCache.query.filter_by(
                    program_code=program_code,
                    cache_date=target_date
                ).first()

                if existing_cache:
                    existing_cache.songs_json = json.dumps(songs)
                    log.debug(f"Updated cache for {program_code}")
                else:
                    cache = SongCache(
                        program_code=program_code,
                        cache_date=target_date,
                        songs_json=json.dumps(songs)
                    )
                    db.session.add(cache)
                    log.debug(f"Cached songs for {program_code}")

                db.session.commit()
            except Exception as e:
                db.session.rollback()
                log.warning(f"Failed to cache songs for {program_code}: {e}")

            return songs
        else:
            log.warning(f"No songs found for {program_code}")
            return None

    except Exception as e:
        log.error(f"Error fetching songs for {program_code}: {e}")
        return None


def _get_user_spotify_client(user):
    """
    Create an authenticated Spotify client for a user.

    Args:
        user (User): User object with encrypted tokens

    Returns:
        spotipy.Spotify: Authenticated Spotify client

    Raises:
        ValueError: If user has no access token
        Exception: If token refresh fails
    """
    access_token = user.get_access_token()

    if not access_token:
        raise ValueError(f'User {user.id} has no Spotify access token')

    # Try to use token directly
    return spotipy.Spotify(auth=access_token)
