#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Spotify client module for managing playlists and searching tracks.

Provides functions for:
- Searching tracks with 3-tier strategy
- Managing playlist creation and modification
- Cleaning artist names
- Handling user authentication and token refresh
"""

import re
import logging
from datetime import datetime

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
    SPOTIPY_AVAILABLE = True
except ImportError:
    SPOTIPY_AVAILABLE = False

log = logging.getLogger(__name__)

DAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]


def clean_artist_name(artist):
    """
    Clean artist name by removing parenthetical info, featured artists,
    and instrument prefixes.

    Removes:
    - Instrument prefixes: "trombone: Christian Lindberg" -> "Christian Lindberg"
    - Content in parentheses: "Artist (Remix)" -> "Artist"
    - Featured artists: "Artist feat. Other" -> "Artist"
    - "of" separator: "Artist of Something" -> "Artist"
    - Secondary performer after comma with instrument:
      "Christian Lindberg, pf: Per Lundberg" -> "Christian Lindberg"

    Args:
        artist (str): Artist name to clean

    Returns:
        str: Cleaned artist name
    """
    # Remove instrument/role prefix at start (including compound prefixes)
    artist = re.sub(
        r"^(pf|vn|vc|gt|bar|sop|ten|bass|fl|ob|cl|hrn|perc|org|hp|"
        r"voc&e-vn|e-vn|voc|"
        r"trombone|trumpet|tuba|cello|violin|piano|soprano|"
        r"baroque harp|viola da gamba|nyckelharpa|accordion|"
        r"pf&지휘|지휘):\s*",
        "",
        artist,
        flags=re.IGNORECASE,
    )
    # Remove secondary performers with instrument prefix after comma
    artist = re.split(r",\s*(?:pf|vn|vc|trombone|piano|gt|지휘):", artist)[0].strip()
    # Remove orchestra/ensemble name after comma (if remainder contains Korean)
    comma_parts = artist.split(",", 1)
    if len(comma_parts) > 1 and re.search(r"[가-힣]", comma_parts[1]) and re.search(r"[A-Za-z]", comma_parts[0]):
        artist = comma_parts[0].strip()
    artist = re.sub(r"\s*\([^)]*\)\s*", " ", artist)
    artist = re.split(r"\s+feat\.?\s+", artist, flags=re.IGNORECASE)[0]
    artist = re.split(r"\s+of\s+", artist, flags=re.IGNORECASE)[0]
    return artist.strip()


def clean_title(title):
    """
    Clean song title for better Spotify search results.

    Handles patterns common in Korean radio playlists:
    - Request codes: "[5080/신청곡] Va Pensiero" -> "Va Pensiero"
    - Korean parenthetical translations: "Erindring (회상)" -> "Erindring"
    - Composer prefixes with Korean titles:
      "Kreisler / 비엔나풍의 작은 행진곡 (Marche Miniature Viennoise)"
      -> title="Marche Miniature Viennoise", composer="Kreisler"
    - Multi-song markers: "Song A + Song B" -> "Song A"

    Args:
        title (str): Raw song title from scraper

    Returns:
        tuple: (cleaned_title, composer_or_none)
    """
    # 1. Remove request code prefixes: [5080/신청곡], [권진희/신청곡], etc.
    title = re.sub(r"\[[^\]]*(?:신청곡|사연)[^\]]*\]\s*", "", title)

    # 2. Remove "+" continuation (multi-song entries)
    title = re.split(r"\s*\+\s+", title)[0].strip()
    # Also split on "& X번" (multi-movement classical entries)
    title = re.split(r"\s*&\s+\d+번", title)[0].strip()

    # 3. Handle "영화 <Name> OST - Title" pattern
    ost_match = re.match(r"영화\s*[<《].*?[>》]\s*OST\s*[-–:]\s*(.+)", title)
    if ost_match:
        title = ost_match.group(1).strip()

    # 4. Handle "Composer / Title" format (e.g., "Kreisler / 비엔나풍의 작은 행진곡")
    composer = None
    composer_match = re.match(r"^([A-Za-z][A-Za-z.\s]+?)\s*/\s*(.+)$", title)
    if composer_match:
        composer = composer_match.group(1).strip()
        title = composer_match.group(2).strip()

    # 5. Remove Korean movement markers: "중 2악장" -> ""
    title = re.sub(r"\s*중\s+\d+악장\s*", " ", title)

    # 6. Handle title with Korean + Western in parentheses
    #    e.g., "비엔나풍의 작은 행진곡 (Marche Miniature Viennoise)"
    #    -> prefer "Marche Miniature Viennoise"
    has_korean = bool(re.search(r"[가-힣]", title))
    if has_korean:
        western_match = re.search(
            r"\(([A-Za-z][A-Za-z\s',\-\.&:]+)\)", title
        )
        if western_match:
            title = western_match.group(1).strip()
            has_korean = False

    # 7. Remove Korean-only parenthetical translations
    #    e.g., "(연애 소설의 결말)", "(회상)", "(보링까노의 애가)"
    title = re.sub(r"\([가-힣\s,·]+\)", "", title)

    # 8. For mixed Korean/Western titles, extract Western parts + catalog numbers
    has_korean = bool(re.search(r"[가-힣]", title))
    if has_korean and re.search(r"[A-Za-z]", title):
        # Remove Korean number markers (X번)
        title = re.sub(r"\d+번", "", title)
        # Remove Korean character sequences
        title = re.sub(r"[가-힣]+", " ", title)

    # 9. Clean up extra whitespace and stray punctuation
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"^[\s,&]+|[\s,&]+$", "", title)

    return title, composer


def search_spotify_track(sp, title, artist):
    """
    Search for a track on Spotify using a 3-tier strategy.

    Before searching, cleans the title to remove Korean radio noise
    (request codes, Korean translations, composer prefixes).

    Tier 1: Search with cleaned title and artist
    Tier 2: General search with cleaned title and artist
    Tier 3: Title-only search (fallback)
    Tier 4: If composer found, search with composer + title

    Args:
        sp (spotipy.Spotify): Authenticated Spotify client
        title (str): Track title
        artist (str): Artist name

    Returns:
        str: Spotify track ID if found, None otherwise
    """
    cleaned_title, composer = clean_title(title)
    cleaned_artist = clean_artist_name(artist) if artist else ""

    log.debug(
        f"Searching: original='{title}' -> cleaned='{cleaned_title}', "
        f"artist='{artist}' -> '{cleaned_artist}', composer='{composer}'"
    )

    # Tier 1: Specific query with cleaned title and artist
    if cleaned_artist:
        query = f"track:{cleaned_title} artist:{cleaned_artist}"
        try:
            results = sp.search(q=query, type="track", limit=3)
            tracks = results.get("tracks", {}).get("items", [])
            if tracks:
                log.debug(f"Found '{cleaned_title}' by '{cleaned_artist}' (Tier 1)")
                return tracks[0]["id"]
        except Exception as e:
            log.debug(f"Tier 1 search failed: {e}")

        # Tier 2: General search with both title and artist
        query = f"{cleaned_title} {cleaned_artist}"
        try:
            results = sp.search(q=query, type="track", limit=3)
            tracks = results.get("tracks", {}).get("items", [])
            if tracks:
                log.debug(f"Found '{cleaned_title}' by '{cleaned_artist}' (Tier 2)")
                return tracks[0]["id"]
        except Exception as e:
            log.debug(f"Tier 2 search failed: {e}")

    # Tier 3: If composer was extracted, search with composer as artist
    if composer:
        query = f"{cleaned_title} {composer}"
        try:
            results = sp.search(q=query, type="track", limit=3)
            tracks = results.get("tracks", {}).get("items", [])
            if tracks:
                log.debug(f"Found '{cleaned_title}' with composer '{composer}' (Tier 3)")
                return tracks[0]["id"]
        except Exception as e:
            log.debug(f"Tier 3 composer search failed: {e}")

    # Tier 4: Title-only search (fallback)
    try:
        results = sp.search(q=cleaned_title, type="track", limit=5)
        tracks = results.get("tracks", {}).get("items", [])
        if tracks:
            log.debug(f"Found '{cleaned_title}' by title-only search (Tier 4)")
            return tracks[0]["id"]
    except Exception as e:
        log.debug(f"Tier 4 search failed: {e}")

    log.debug(f"Could not find '{title}' by '{artist}' on Spotify")
    return None


def find_playlist(sp, target_name):
    """
    Find a playlist by name.

    Args:
        sp (spotipy.Spotify): Authenticated Spotify client
        target_name (str): Playlist name to search for

    Returns:
        str: Playlist ID if found, None otherwise
    """
    try:
        offset = 0
        while True:
            playlists = sp.current_user_playlists(limit=50, offset=offset)
            items = playlists.get("items", [])
            if not items:
                break

            for pl in items:
                if pl["name"] == target_name:
                    log.debug(f"Found existing playlist: '{target_name}'")
                    return pl["id"]

            offset += 50
            if offset >= playlists.get("total", 0):
                break

        log.debug(f"Playlist not found: '{target_name}'")
        return None
    except Exception as e:
        log.error(f"Error finding playlist '{target_name}': {e}")
        return None


def find_or_create_playlist(sp, playlist_name):
    """
    Find an existing playlist or create a new one.

    Args:
        sp (spotipy.Spotify): Authenticated Spotify client
        playlist_name (str): Name of the playlist

    Returns:
        tuple: (playlist_id, is_new) where is_new is True if playlist was created
    """
    try:
        playlist_id = find_playlist(sp, playlist_name)
        if playlist_id:
            return playlist_id, False

        user = sp.current_user()
        new_playlist = sp.user_playlist_create(
            user=user["id"],
            name=playlist_name,
            public=False,
            description="Auto-generated by Radio Playlist Script",
        )
        log.info(f"Created new playlist: '{playlist_name}'")
        return new_playlist["id"], True
    except Exception as e:
        log.error(f"Error managing playlist '{playlist_name}': {e}")
        raise


def get_user_spotify_client(user, client_id, client_secret, redirect_uri, token_cache_path):
    """
    Create an authenticated Spotify client for a user.

    Handles token refresh if needed. Uses cached token if available.

    Args:
        user (User): User object with spotify_token_data dict containing:
            - 'access_token': Current access token
            - 'refresh_token': Refresh token for renewal
            - 'token_expire_at': Unix timestamp of expiration
        client_id (str): Spotify API client ID
        client_secret (str): Spotify API client secret
        redirect_uri (str): OAuth redirect URI
        token_cache_path (str): Path to cache tokens (optional, can be None)

    Returns:
        spotipy.Spotify: Authenticated Spotify client

    Raises:
        ValueError: If user has no stored Spotify token data
    """
    if not user.spotify_token_data:
        raise ValueError("User has no Spotify token data")

    token_data = user.spotify_token_data
    access_token = token_data.get("access_token")

    if not access_token:
        raise ValueError("User has no access token")

    # Try to refresh if token is expired or about to expire
    if _is_token_expired(token_data):
        log.debug(f"Token expired for user {user.id}, refreshing...")
        refresh_token = token_data.get("refresh_token")
        if refresh_token:
            token_data = refresh_user_token(
                token_data, client_id, client_secret
            )
            user.spotify_token_data = token_data
            user.save()
            access_token = token_data.get("access_token")

    return spotipy.Spotify(auth=access_token)


def refresh_user_token(token_data, client_id, client_secret):
    """
    Refresh an expired Spotify access token using the refresh token.

    Args:
        token_data (dict): Token data dict with 'refresh_token' key
        client_id (str): Spotify API client ID
        client_secret (str): Spotify API client secret

    Returns:
        dict: Updated token data with new access_token and expiration

    Raises:
        Exception: If token refresh fails
    """
    try:
        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            raise ValueError("No refresh token available")

        auth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri="http://localhost:8080/callback",
        )

        new_token = auth.refresh_access_token(refresh_token)

        token_data["access_token"] = new_token["access_token"]
        token_data["expires_in"] = new_token.get("expires_in", 3600)
        token_data["token_expire_at"] = (
            datetime.now().timestamp() + new_token.get("expires_in", 3600)
        )

        if "refresh_token" in new_token:
            token_data["refresh_token"] = new_token["refresh_token"]

        log.info("Spotify token refreshed successfully")
        return token_data
    except Exception as e:
        log.error(f"Failed to refresh Spotify token: {e}")
        raise


def _is_token_expired(token_data):
    """
    Check if a token is expired or about to expire.

    Considers token expired if it expires within 5 minutes.

    Args:
        token_data (dict): Token data dict with 'token_expire_at' key

    Returns:
        bool: True if token is expired or expiring soon, False otherwise
    """
    expire_at = token_data.get("token_expire_at")
    if not expire_at:
        return True

    current_time = datetime.now().timestamp()
    return expire_at - current_time < 300


def get_playlist_name(program, now=None):
    """
    Generate a playlist name from program info and date.

    Format: "{program_name} {date}({day_name})"
    Example: "이상순 2024.0210(월)"

    Args:
        program (dict): Program dict with 'name' key
        now (datetime, optional): Datetime object. Defaults to current time.

    Returns:
        str: Formatted playlist name
    """
    if now is None:
        now = datetime.now()

    day_name = DAY_NAMES[now.weekday()]
    return f"{program['name']} {now.strftime('%Y.%m%d')}({day_name})"
