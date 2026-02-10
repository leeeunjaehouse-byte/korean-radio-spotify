#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JSON API blueprint for program management and playlist operations.
"""

from flask import Blueprint, jsonify, request, session, current_app
from app.models import db, User, UserProgram, UserPlaylist, SongCache
from app.blueprints.auth import login_required
from app import radio_scraper, spotify_client
from datetime import datetime, date
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
import spotipy
import logging
import json

log = logging.getLogger(__name__)

api_bp = Blueprint('api', __name__)


# ─── Program Follow/Unfollow ────────────────────────────────

@api_bp.route('/programs/follow', methods=['POST'])
@login_required
def follow_program():
    """Follow a program"""
    user_id = session.get('user_id')
    data = request.get_json(silent=True)

    if not data or 'program_code' not in data:
        return jsonify({'error': 'program_code is required'}), 400

    program_code = data.get('program_code')
    programs = current_app.config.get('PROGRAMS', [])
    program = next((p for p in programs if p.get('prog_code') == program_code), None)

    if not program:
        return jsonify({'error': 'Program not found'}), 404

    try:
        user_program = UserProgram(user_id=user_id, program_code=program_code)
        db.session.add(user_program)
        db.session.commit()
        log.info(f"User {user_id} followed program {program_code}")
        return jsonify({'success': True, 'message': f"{program.get('name')} 구독 완료"}), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Already following this program'}), 409
    except Exception as e:
        db.session.rollback()
        log.error(f"Error following program: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@api_bp.route('/programs/unfollow', methods=['POST'])
@login_required
def unfollow_program():
    """Unfollow a program"""
    user_id = session.get('user_id')
    data = request.get_json(silent=True)

    if not data or 'program_code' not in data:
        return jsonify({'error': 'program_code is required'}), 400

    program_code = data.get('program_code')

    try:
        user_program = UserProgram.query.filter_by(
            user_id=user_id, program_code=program_code
        ).first()

        if not user_program:
            return jsonify({'error': 'Not following this program'}), 404

        db.session.delete(user_program)
        db.session.commit()
        log.info(f"User {user_id} unfollowed program {program_code}")
        return jsonify({'success': True, 'message': '구독 취소 완료'}), 200
    except Exception as e:
        db.session.rollback()
        log.error(f"Error unfollowing program: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@api_bp.route('/programs/status', methods=['GET'])
@login_required
def programs_status():
    """Get all programs with follow status for current user"""
    user_id = session.get('user_id')
    programs = current_app.config.get('PROGRAMS', [])

    user_program_codes = db.session.query(UserProgram.program_code).filter_by(
        user_id=user_id
    ).all()
    followed_set = {up[0] for up in user_program_codes}

    result = []
    for p in programs:
        result.append({
            'prog_code': p.get('prog_code'),
            'name': p.get('name'),
            'station': p.get('station'),
            'source': p.get('source'),
            'description': p.get('description'),
            'is_followed': p.get('prog_code') in followed_set
        })

    return jsonify(result), 200


# ─── Playlists ──────────────────────────────────────────────

@api_bp.route('/playlists', methods=['GET'])
@login_required
def get_playlists():
    """Get user's recent playlist history"""
    user_id = session.get('user_id')

    playlists = UserPlaylist.query.filter_by(user_id=user_id).order_by(
        UserPlaylist.created_date.desc()
    ).limit(30).all()

    programs = current_app.config.get('PROGRAMS', [])
    program_map = {p.get('prog_code'): p for p in programs}

    playlist_data = []
    for pl in playlists:
        program = program_map.get(pl.program_code, {})
        playlist_data.append({
            'id': pl.id,
            'program_code': pl.program_code,
            'program_name': program.get('name', pl.program_code),
            'program_station': program.get('station', ''),
            'created_date': pl.created_date.isoformat(),
            'spotify_playlist_id': pl.spotify_playlist_id,
            'spotify_playlist_url': pl.spotify_playlist_url,
            'playlist_name': pl.playlist_name,
            'total_songs': pl.total_songs,
            'songs_added': pl.songs_added,
            'songs_not_found': pl.songs_not_found,
            'created_at': pl.created_at.isoformat()
        })

    return jsonify(playlist_data), 200


@api_bp.route('/playlists/create-now', methods=['POST'])
@login_required
def create_playlist_now():
    """Manually trigger playlist creation for today"""
    user_id = session.get('user_id')
    data = request.get_json(silent=True) or {}
    program_code = data.get('program_code')

    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404

        if program_code:
            user_programs = UserProgram.query.filter_by(
                user_id=user_id, program_code=program_code
            ).all()
        else:
            user_programs = UserProgram.query.filter_by(user_id=user_id).all()

        if not user_programs:
            return jsonify({'error': '구독 중인 프로그램이 없습니다'}), 400

        programs = current_app.config.get('PROGRAMS', [])
        program_map = {p.get('prog_code'): p for p in programs}

        results = []
        for up in user_programs:
            pc = up.program_code
            program = program_map.get(pc)
            if not program:
                results.append({'program_code': pc, 'success': False, 'error': 'Program not found'})
                continue
            try:
                result = _create_playlist_for_program(user, program)
                results.append({'program_code': pc, 'program_name': program.get('name'), **result})
            except Exception as e:
                log.error(f"Error creating playlist for {pc}: {e}")
                results.append({'program_code': pc, 'program_name': program.get('name'), 'success': False, 'error': str(e)})

        return jsonify({'success': True, 'timestamp': datetime.utcnow().isoformat(), 'results': results}), 200

    except Exception as e:
        log.error(f"Error in create_playlist_now: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ─── Admin API ──────────────────────────────────────────────

@api_bp.route('/admin/stats', methods=['GET'])
@login_required
def admin_stats():
    """Get admin statistics"""
    total_users = User.query.filter_by(is_active=True).count()
    total_playlists = UserPlaylist.query.count()
    total_songs = db.session.query(func.sum(UserPlaylist.songs_added)).scalar() or 0

    # Last job run - approximate from latest playlist creation
    last_playlist = UserPlaylist.query.order_by(UserPlaylist.created_at.desc()).first()
    last_run_at = last_playlist.created_at.isoformat() if last_playlist else None

    return jsonify({
        'total_users': total_users,
        'total_playlists': total_playlists,
        'total_songs': total_songs,
        'last_run_at': last_run_at
    })


@api_bp.route('/admin/cache-status', methods=['GET'])
@login_required
def admin_cache_status():
    """Get cache status for all programs"""
    programs = current_app.config.get('PROGRAMS', [])
    cache_status = {}

    for p in programs:
        pc = p.get('prog_code')
        cache = SongCache.query.filter_by(program_code=pc).order_by(
            SongCache.cache_date.desc()
        ).first()

        if cache:
            try:
                songs = json.loads(cache.songs_json)
                songs_count = len(songs)
            except Exception:
                songs_count = 0
            cache_status[pc] = {
                'songs_count': songs_count,
                'last_update': cache.fetched_at.isoformat() if cache.fetched_at else None
            }
        else:
            cache_status[pc] = {'songs_count': 0, 'last_update': None}

    return jsonify({'cache_status': cache_status})


@api_bp.route('/admin/update-cache/<program_code>', methods=['POST'])
@login_required
def admin_update_cache(program_code):
    """Update cache for a specific program"""
    programs = current_app.config.get('PROGRAMS', [])
    program = next((p for p in programs if p.get('prog_code') == program_code), None)

    if not program:
        return jsonify({'error': 'Program not found'}), 404

    try:
        songs = radio_scraper.fetch_songs(program)
        today = date.today()

        if songs:
            existing = SongCache.query.filter_by(program_code=program_code, cache_date=today).first()
            if existing:
                existing.songs_json = json.dumps(songs)
                existing.fetched_at = datetime.utcnow()
            else:
                cache = SongCache(
                    program_code=program_code,
                    cache_date=today,
                    songs_json=json.dumps(songs)
                )
                db.session.add(cache)
            db.session.commit()
            return jsonify({'success': True, 'message': f'{len(songs)}곡 캐시 업데이트 완료'})
        else:
            return jsonify({'success': False, 'message': '오늘 선곡표를 찾을 수 없습니다'}), 404
    except Exception as e:
        db.session.rollback()
        log.error(f"Error updating cache: {e}")
        return jsonify({'error': str(e)}), 500


@api_bp.route('/admin/run-collect-songs', methods=['POST'])
@login_required
def admin_run_collect_songs():
    """Manually collect songs for all programs"""
    programs = current_app.config.get('PROGRAMS', [])
    today = date.today()
    collected = 0

    for p in programs:
        try:
            songs = radio_scraper.fetch_songs(p)
            if songs:
                pc = p.get('prog_code')
                existing = SongCache.query.filter_by(program_code=pc, cache_date=today).first()
                if existing:
                    existing.songs_json = json.dumps(songs)
                    existing.fetched_at = datetime.utcnow()
                else:
                    cache = SongCache(program_code=pc, cache_date=today, songs_json=json.dumps(songs))
                    db.session.add(cache)
                collected += 1
        except Exception as e:
            log.error(f"Error collecting songs for {p.get('name')}: {e}")

    db.session.commit()
    return jsonify({'success': True, 'message': f'{collected}/{len(programs)} 프로그램 수집 완료'})


@api_bp.route('/admin/run-create-playlists', methods=['POST'])
@login_required
def admin_run_create_playlists():
    """Manually trigger daily playlist creation"""
    from app.jobs import daily_create_playlists
    try:
        daily_create_playlists(current_app._get_current_object())
        return jsonify({'success': True, 'message': '모든 사용자 플레이리스트 생성 완료'})
    except Exception as e:
        log.error(f"Error running create playlists: {e}")
        return jsonify({'error': str(e)}), 500


@api_bp.route('/admin/clear-cache', methods=['POST'])
@login_required
def admin_clear_cache():
    """Clear all song cache"""
    try:
        count = SongCache.query.delete()
        db.session.commit()
        return jsonify({'success': True, 'message': f'{count}개 캐시 항목 삭제 완료'})
    except Exception as e:
        db.session.rollback()
        log.error(f"Error clearing cache: {e}")
        return jsonify({'error': str(e)}), 500


@api_bp.route('/admin/program-details', methods=['GET'])
@login_required
def admin_program_details():
    """Get detailed stats for each program"""
    programs = current_app.config.get('PROGRAMS', [])
    details = {}

    for p in programs:
        pc = p.get('prog_code')
        followers = UserProgram.query.filter_by(program_code=pc).count()
        playlists_count = UserPlaylist.query.filter_by(program_code=pc).count()
        total_songs = db.session.query(func.sum(UserPlaylist.songs_added)).filter(
            UserPlaylist.program_code == pc
        ).scalar() or 0

        details[pc] = {
            'followers': followers,
            'playlists_count': playlists_count,
            'total_songs': total_songs
        }

    return jsonify({'program_details': details})


# ─── Helper Functions ───────────────────────────────────────

def _create_playlist_for_program(user, program):
    """Helper function to create a playlist for a single program"""
    program_code = program.get('prog_code')
    today = date.today()

    existing = UserPlaylist.query.filter_by(
        user_id=user.id, program_code=program_code, created_date=today
    ).first()

    if existing:
        return {'success': False, 'error': '오늘 이미 생성됨'}

    songs = _fetch_or_cache_songs(program, today)
    if not songs:
        return {'success': False, 'error': '선곡표를 찾을 수 없습니다'}

    try:
        sp = _get_user_spotify_client(user)
    except Exception as e:
        return {'success': False, 'error': f'Spotify 인증 오류: {str(e)}'}

    playlist_name = spotify_client.get_playlist_name(program, datetime.now())

    try:
        playlist_id, is_new = spotify_client.find_or_create_playlist(sp, playlist_name)

        track_ids = []
        not_found_count = 0
        for song in songs:
            track_id = spotify_client.search_spotify_track(sp, song.get('title'), song.get('artist'))
            if track_id:
                track_ids.append(track_id)
            else:
                not_found_count += 1

        added_count = 0
        if track_ids:
            try:
                sp.playlist_add_items(playlist_id, track_ids)
                added_count = len(track_ids)
            except Exception as e:
                log.warning(f"Error adding items to playlist: {e}")

        playlist_info = sp.playlist(playlist_id)
        playlist_url = playlist_info.get('external_urls', {}).get('spotify', '')

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

        return {
            'success': True,
            'playlist_id': playlist_id,
            'playlist_url': playlist_url,
            'playlist_name': playlist_name,
            'total_songs': len(songs),
            'songs_added': added_count,
            'songs_not_found': not_found_count
        }
    except Exception as e:
        log.error(f"Error creating playlist: {e}")
        return {'success': False, 'error': str(e)}


def _fetch_or_cache_songs(program, target_date):
    """Fetch songs from cache or scrape and cache them"""
    program_code = program.get('prog_code')

    cache = SongCache.query.filter_by(program_code=program_code, cache_date=target_date).first()
    if cache:
        try:
            return json.loads(cache.songs_json)
        except json.JSONDecodeError:
            pass

    try:
        songs = radio_scraper.fetch_songs(program)
        if songs:
            try:
                existing = SongCache.query.filter_by(program_code=program_code, cache_date=target_date).first()
                if existing:
                    existing.songs_json = json.dumps(songs)
                else:
                    new_cache = SongCache(program_code=program_code, cache_date=target_date, songs_json=json.dumps(songs))
                    db.session.add(new_cache)
                db.session.commit()
            except Exception:
                db.session.rollback()
        return songs
    except Exception as e:
        log.error(f"Error fetching songs for {program_code}: {e}")
        return None


def _get_user_spotify_client(user):
    """Create an authenticated Spotify client for a user with token refresh"""
    from app.blueprints.auth import get_spotify_oauth

    # Check if token is expired
    if user.token_expires_at and user.token_expires_at < datetime.utcnow():
        refresh_token = user.get_refresh_token()
        if refresh_token:
            try:
                sp_oauth = get_spotify_oauth()
                new_token = sp_oauth.refresh_access_token(refresh_token)
                user.set_access_token(new_token['access_token'])
                if 'refresh_token' in new_token:
                    user.set_refresh_token(new_token['refresh_token'])
                user.token_expires_at = datetime.fromtimestamp(new_token['expires_at'])
                db.session.commit()
                return spotipy.Spotify(auth=new_token['access_token'])
            except Exception as e:
                log.error(f"Token refresh failed for user {user.id}: {e}")
                raise ValueError(f'Token refresh failed: {e}')

    access_token = user.get_access_token()
    if not access_token:
        raise ValueError('User has no Spotify access token')
    return spotipy.Spotify(auth=access_token)
