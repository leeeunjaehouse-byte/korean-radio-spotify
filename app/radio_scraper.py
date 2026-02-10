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

    Handles both inline and separated formats:
    - Inline: "1. Song Title pf: Artist Name"
    - Separated: "1. Song Title" / "pf: Artist Name"

    Args:
        lines (list): List of text lines

    Returns:
        list: List of dicts with 'title' and 'artist' keys
    """
    songs = []
    dur_re = re.compile(r"\d+'\d+")
    num_re = re.compile(r"^(\d+)\.\s*(.+)")
    inst_re = re.compile(
        r"(pf|vn|vc|gt|bar|sop|ten|bass|fl|ob|cl|hrn|perc|org|hp|"
        r"voc|trombone|trumpet|tuba|cello|violin|piano|soprano|"
        r"baroque harp|viola da gamba|nyckelharpa|accordion):\s*",
        re.IGNORECASE,
    )
    skip_words = ["뮤직 인사이드", "세상의 모든 음악 Logo", "저녁에 쉼표"]

    i = 0
    while i < len(lines):
        line = lines[i]

        # Skip section headers
        if any(h in line for h in skip_words) and not num_re.match(line):
            i += 1
            continue

        # Skip time-only lines
        if dur_re.fullmatch(line):
            i += 1
            continue

        num_m = num_re.match(line)
        if not num_m:
            i += 1
            continue

        title = num_m.group(2).strip()
        artist = ""

        # Case 1: Duration included in title line (inline format)
        if dur_re.search(title):
            inst_m = inst_re.search(title)
            if inst_m:
                song_title = title[: inst_m.start()].strip()
                rest = title[inst_m.end() :]
                artist = dur_re.sub("", rest).strip()
                artist = re.split(r",\s*지휘:", artist)[0].strip().rstrip(",")
            else:
                song_title = dur_re.sub("", title).strip()
                artist = ""

            if song_title:
                songs.append({"title": song_title, "artist": artist})
            i += 1
            continue

        # Case 2: Separated format - next line is artist
        if i + 1 < len(lines):
            nxt = lines[i + 1]

            # Skip "+" continuation lines (multi-song entries)
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith("+"):
                j += 1
            if j > i + 1:
                nxt = lines[j] if j < len(lines) else ""

            if nxt and not num_re.match(nxt) and not any(h in nxt for h in skip_words):
                if dur_re.fullmatch(nxt):
                    i = j + 1
                else:
                    inst_m = inst_re.match(nxt)
                    if inst_m:
                        artist = nxt[inst_m.end() :].strip()
                    else:
                        artist = nxt.strip()
                    artist = re.split(r",\s*지휘:", artist)[0].strip().rstrip(",")

                    if j + 1 < len(lines) and dur_re.fullmatch(lines[j + 1].strip()):
                        i = j + 2
                    else:
                        i = j + 1
            else:
                i = j if j > i + 1 else i + 1
        else:
            i += 1

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
