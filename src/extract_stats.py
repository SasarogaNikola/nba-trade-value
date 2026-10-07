"""
extract_stats.py: pull player statistics from nba_api.

What this file does (step 1):
  1. Calls the LeagueDashPlayerStats endpoint for one season (set in config.py).
  2. Retries the call if it fails and pauses between attempts.
  3. Saves the RAW response to data/raw/ (cache), so we do not call the API twice.
  4. Turns the response into a pandas DataFrame and prints a short overview.

Run it from the project root folder:
    python -m src.extract_stats
"""

import json
import logging
import time

import pandas as pd
from nba_api.stats.endpoints import leaguedashplayerstats

import config

# logging is more professional than print: it shows the time and the message level.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def call_with_retry(make_call):
    """
    Runs make_call() and repeats it if it raises an error.

    make_call is a function with no arguments that performs the actual API call.
    The pause grows with every attempt (5s, 10s, 15s...). This is called
    "linear backoff": if the server is overloaded, we give it more time.
    """
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return make_call()
        except Exception as err:  # nba_api can raise many kinds of errors (timeout, JSON...)
            log.warning("Attempt %d/%d failed: %s", attempt, config.MAX_RETRIES, err)
            if attempt == config.MAX_RETRIES:
                raise  # last attempt: pass the error on, do not swallow it
            time.sleep(config.RETRY_PAUSE * attempt)


def raw_cache_path(season: str):
    """Path of the cache file for a given season, e.g. data/raw/player_base_2025-26.json"""
    return config.RAW_DIR / f"player_base_{season}.json"


def fetch_player_stats_raw(season: str) -> dict:
    """
    Returns the RAW API response (a dictionary) for all players in a season.
    If the cache file already exists, it reads it instead of calling the API.
    """
    cache_file = raw_cache_path(season)

    # 1) Cache hit: no network call.
    if cache_file.exists():
        log.info("Reading from cache: %s", cache_file.name)
        return json.loads(cache_file.read_text(encoding="utf-8"))

    # 2) Cache miss: call the API.
    log.info("Calling nba_api for season %s ...", season)
    endpoint = call_with_retry(
        lambda: leaguedashplayerstats.LeagueDashPlayerStats(
            season=season,
            season_type_all_star=config.SEASON_TYPE,
            per_mode_detailed="Totals",            # season totals (not per game)
            measure_type_detailed_defense="Base",  # basic stats (points, minutes...)
            timeout=config.REQUEST_TIMEOUT,
        )
    )

    raw_json = endpoint.get_json()  # raw JSON text, exactly as the server sent it

    # Save it to disk so we never have to download it again.
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(raw_json, encoding="utf-8")
    log.info("Saved to: %s", cache_file)

    time.sleep(config.CALL_PAUSE)  # pause before the next call (used later)
    return json.loads(raw_json)


def raw_to_dataframe(raw: dict) -> pd.DataFrame:
    """
    Turns the raw response into a DataFrame.

    The nba_api response looks roughly like this:
      {"resultSets": [{"name": "LeagueDashPlayerStats",
                       "headers": ["PLAYER_ID", "PLAYER_NAME", ...],
                       "rowSet":  [[203999, "Nikola Jokic", ...], ...]}]}
    So: headers = column names, rowSet = rows.
    """
    result_set = raw["resultSets"][0]
    return pd.DataFrame(result_set["rowSet"], columns=result_set["headers"])


def main():
    raw = fetch_player_stats_raw(config.SEASON)
    df = raw_to_dataframe(raw)

    print("\n=== DATA OVERVIEW ===")
    print(f"Season: {config.SEASON}")
    print(f"Number of rows (players): {len(df)}")
    print(f"Number of columns: {df.shape[1]}")
    print(f"Number of distinct teams: {df['TEAM_ABBREVIATION'].nunique()}")
    print(f"Duplicates by PLAYER_ID: {df['PLAYER_ID'].duplicated().sum()}")

    print("\nFirst 5 rows (selected columns):")
    cols = ["PLAYER_NAME", "TEAM_ABBREVIATION", "GP", "MIN"]
    print(df[cols].head().to_string(index=False))


if __name__ == "__main__":
    main()
