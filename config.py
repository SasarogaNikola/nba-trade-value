"""
config.py: all project settings in one place.

Idea: no other file hardcodes the season, paths or request limits.
To switch to a different season, change SEASON here and nothing else.
"""

from pathlib import Path

# --- Season ---------------------------------------------------------------
# nba_api expects the format "YYYY-YY". The 2025-26 season ended in June 2026.
SEASON = "2025-26"
SEASON_TYPE = "Regular Season"  # regular season only (no playoffs)

# --- Paths ----------------------------------------------------------------
# Path(__file__) is the path of this file, .parent is the folder it lives in.
# This way the paths work no matter where the script is launched from.
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"          # raw API responses and scraped pages
DB_PATH = DATA_DIR / "nba.db"       # SQLite database (created in the load step)

# --- API call rules -------------------------------------------------------
REQUEST_TIMEOUT = 60    # seconds; stats.nba.com can be slow
MAX_RETRIES = 3         # how many attempts before giving up
RETRY_PAUSE = 5         # seconds to wait before a retry (grows with each attempt)
CALL_PAUSE = 2          # seconds to wait between two successful calls (be polite)

# --- Analysis scope -------------------------------------------------------
TOP_N_PLAYERS_PER_TEAM = 8   # top 8 players by minutes from each team
