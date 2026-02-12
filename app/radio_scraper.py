#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Radio station scraper module for Korean radio programs.

Supports:
- MBC: MiniBeb scraper
- KBS: KONG API
- KBS Board: HTML parsing of board posts
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re
import html as html_module
import logging

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

KBS_BOARD_HEADERS = {
    **HEADERS,
    "Referer": "https://pbbs.kbs.co.kr/",
    "Origin": "https://pbbs.kbs.co.kr",
}


def fetch_mbc_songs(prog_code, date_str=None):
    """
    Fetch songs from MBC miniweb.

    Args:
        prog_code (str): MBC program code (e.g., 'FM4U000001364')
        date_str (str, optional): Date in YYYY-MM-DD format. Defaults to today.

    Returns:
        list: List of dicts with 'title' and 'artist' keys, or None if not found.
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    try:
        for page in range(1, 5):
            list_url = f"https://miniweb.imbc.com/Music?page={page}&progCode={prog_code}"
            resp = requests.get(list_url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select("table tbody tr")

            for row in rows:
                cells = row.select("td")
                if cells and date_str in cells[0].text.strip():
                    link = row.select_one("a")
                    if link:
                        href = link.get("href", "")
                        match = re.search(r"seqID=(\d+)", href)
                        if match:
                            seq_id = match.group(1)
                            view_url = f"https://miniweb.imbc.com/Music/View?seqID={seq_id}&progCode={prog_code}&page=1"
                            resp2 = requests.get(view_url, headers=HEADERS, timeout=15)
                            resp2.raise_for_status()
                            soup2 = BeautifulSoup(resp2.text, "html.parser")
                            songs = []
                            for r in soup2.select("table tbody tr"):
                                c = r.select("td")
                                if len(c) >= 3:
                                    t = c[1].text.strip()
                                    a = c[2].text.strip()
                                    if t and a:
                                        songs.append({"title": t, "artist": a})
                            return songs if songs else None
                    return None
        return None
    except Exception as e:
        log.error(f"Error fetching MBC songs: {e}")
        return None


def fetch_kbs_songs(prog_code, date_str=None):
    """
    Fetch songs from KBS KONG API.

    Args:
        prog_code (str): KBS program code (e.g., 'R2007-0069')
        date_str (str, optional): Date in YYYYMMDD format. Defaults to today.

    Returns:
        list: List of dicts with 'title' and 'artist' keys, or None if not found.
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    try:
        api_url = "https://kong2017.kbs.co.kr/api/mobile/select_song_list"
        params = {
            "program_code": prog_code,
            "rtype": "json",
            "request_date": date_str,
            "page": 1,
            "page_size": 100,
        }
        resp = requests.get(api_url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        songs = []
        for item in data.get("items", []):
            t = item.get("song_title", "").strip()
            a = item.get("artist", "").strip()
            if t and a:
                songs.append({"title": t, "artist": a})

        return songs if songs else None
    except Exception as e:
        log.error(f"Error fetching KBS songs: {e}")
        return None


def fetch_kbs_board_songs(bbs_id, date_str=None):
    """
    Fetch songs from KBS board API with HTML parsing.

    Args:
        bbs_id (str): KBS board ID (e.g., 'R2007-0077-03-821927')
        date_str (str, optional): Date in YYYY-MM-DD format. Defaults to today.

    Returns:
        list: List of dicts with 'title' and 'artist' keys, or None if not found.
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    try:
        # 1) Fetch post list
        list_url = "https://cfpbbsapi.kbs.co.kr/board/v1/list"
        resp = requests.get(
            list_url,
            headers=KBS_BOARD_HEADERS,
            params={
                "bbs_id": bbs_id,
                "page": 1,
                "page_size": 15,
                "contents_yn": "N",
                "notice_yn": "N",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        # 2) Find post matching the date
        parts = date_str.split("-")
        month, day = int(parts[1]), int(parts[2])
        target = f"{month}월 {day}일"

        post = None
        for p in data.get("data", []):
            if target in p.get("post_title", ""):
                post = p
                break

        if not post:
            return None

        # 3) Fetch post content
        read_url = "https://cfpbbsapi.kbs.co.kr/board/v1/read_post"
        resp2 = requests.get(
            read_url,
            headers=KBS_BOARD_HEADERS,
            params={"bbs_id": bbs_id, "id": post["id"], "post_no": post["post_no"]},
            timeout=15,
        )
        resp2.raise_for_status()
        html_content = resp2.json().get("post", {}).get("post_contents", "")

        if not html_content:
            return None

        # 4) Parse HTML to text lines
        text = re.sub(r"</div>", "\n", html_content, flags=re.IGNORECASE)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = html_module.unescape(text)
        lines = [l.strip() for l in text.split("\n") if l.strip()]

        # 5) Parse songs from text
        songs = _parse_kbs_board_songs(lines)
        return songs if songs else None
    except Exception as e:
        log.error(f"Error fetching KBS board songs: {e}")
        return None


def _parse_kbs_board_songs(lines):
    """
    Parse song list from KBS board text lines.

    Uses a block-based approach:
    1. Find all numbered entries and their positions
    2. For each entry, collect lines until the next entry
    3. Find the duration line, work backwards to find the artist
    4. Everything between the title line and artist is title continuation

    This handles multi-line classical music titles like:
      5. [3576/신청곡] J.S.Bach / 무반주 바이올린 소나타
      1번 g minor, BWV.1001 중 3악장 Siciliana
      vn: 정경화
      3'14 / 3'29

    Args:
        lines (list): List of text lines

    Returns:
        list: List of dicts with 'title' and 'artist' keys
    """
    songs = []
    dur_re = re.compile(r"\d+'\d+")
    num_re = re.compile(r"^(\d+)\.\s*(.+)")
    inst_re = re.compile(
        r"^(pf|vn|vc|gt|bar|sop|ten|bass|fl|ob|cl|hrn|perc|org|hp|"
        r"voc&e-vn|e-vn|voc|trombone|trumpet|tuba|cello|violin|piano|soprano|"
        r"baroque harp|viola da gamba|nyckelharpa|accordion|"
        r"pf&지휘|지휘):\s*",
        re.IGNORECASE,
    )
    skip_words = ["뮤직 인사이드", "세상의 모든 음악 Logo", "저녁에 쉼표"]

    # Step 1: Find all numbered entries and their positions
    entry_indices = []
    for idx, line in enumerate(lines):
        if any(h in line for h in skip_words) and not num_re.match(line):
            continue
        num_m = num_re.match(line)
        if num_m:
            entry_indices.append((idx, num_m.group(2).strip()))

    # Step 2: Process each entry's block
    for e_idx, (start_idx, first_title) in enumerate(entry_indices):
        # Determine end of this entry's block
        if e_idx + 1 < len(entry_indices):
            end_idx = entry_indices[e_idx + 1][0]
        else:
            end_idx = len(lines)

        # Collect inner lines (between numbered line and next entry)
        block = []
        for bi in range(start_idx + 1, end_idx):
            bl = lines[bi].strip()
            if not bl:
                continue
            if any(h in bl for h in skip_words):
                continue
            block.append(bl)

        # --- Case 1: Duration in the title line (inline format) ---
        if dur_re.search(first_title):
            inst_m = inst_re.search(first_title)
            if inst_m:
                song_title = first_title[: inst_m.start()].strip()
                rest = first_title[inst_m.end():]
                artist = dur_re.sub("", rest).strip()
                artist = re.split(r",\s*지휘:", artist)[0].strip().rstrip(",")
            else:
                song_title = dur_re.sub("", first_title).strip()
                artist = ""
            if song_title:
                songs.append({"title": song_title, "artist": artist})
            continue

        # --- Case 2: Separated format - use block to find artist ---
        title_parts = [first_title]
        artist = ""

        if not block:
            songs.append({"title": first_title, "artist": ""})
            continue

        # Find the LAST pure duration line in the block
        dur_line_idx = None
        for bi in range(len(block) - 1, -1, -1):
            bl = block[bi]
            clean = dur_re.sub("", bl).replace("/", "").replace(" ", "").strip()
            if dur_re.search(bl) and not clean:
                dur_line_idx = bi
                break

        if dur_line_idx is not None and dur_line_idx > 0:
            # Find artist line: last significant line before duration
            # Skip note lines (starting with *)
            artist_idx = dur_line_idx - 1
            while artist_idx >= 0 and block[artist_idx].startswith("*"):
                artist_idx -= 1

            if artist_idx >= 0:
                artist_line = block[artist_idx]
                # Lines before artist_idx are title continuation
                for ti in range(0, artist_idx):
                    if not block[ti].startswith("+"):
                        title_parts.append(block[ti])

                # Extract artist from artist line
                inst_m = inst_re.match(artist_line)
                if inst_m:
                    artist = artist_line[inst_m.end():].strip()
                else:
                    artist = artist_line.strip()
                # Remove secondary 지휘: info after comma
                artist = re.split(r",\s*지휘:", artist)[0].strip().rstrip(",")
        elif dur_line_idx == 0:
            # Duration is first line in block, no artist found
            pass
        else:
            # No duration line found; use first non-skip block line as artist
            artist_line = block[0]
            inst_m = inst_re.match(artist_line)
            if inst_m:
                artist = artist_line[inst_m.end():].strip()
            else:
                artist = artist_line.strip()
            artist = re.split(r",\s*지휘:", artist)[0].strip().rstrip(",")

        title = " ".join(title_parts)
        if title:
            songs.append({"title": title, "artist": artist})

    return songs


def fetch_songs(program, date_str=None):
    """
    Fetch songs from a program based on its source.

    Routes to the appropriate fetcher based on program['source']:
    - 'mbc': fetch_mbc_songs
    - 'kbs': fetch_kbs_songs
    - 'kbs_board': fetch_kbs_board_songs

    Args:
        program (dict): Program dict with 'source', 'prog_code', and optional 'bbs_id'
        date_str (str, optional): Date string. Format depends on source.

    Returns:
        list: List of dicts with 'title' and 'artist' keys, or None if not found.

    Raises:
        ValueError: If program source is unknown.
    """
    source = program.get("source")

    if source == "mbc":
        return fetch_mbc_songs(program["prog_code"], date_str)
    elif source == "kbs":
        return fetch_kbs_songs(program["prog_code"], date_str)
    elif source == "kbs_board":
        return fetch_kbs_board_songs(program["bbs_id"], date_str)
    else:
        raise ValueError(f"Unknown source: {source}")
