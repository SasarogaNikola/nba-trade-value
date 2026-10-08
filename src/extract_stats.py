"""
extract_stats.py: pull player statistics from nba_api.

What this file does:
  1. Downloads GAME-BY-GAME player logs for one season (set in config.py).
     One row = one player in one game, with the team he played for in that game.
  2. Retries the call if it fails and pauses between attempts.
  3. Saves the RAW response to data/raw/ (cache), so we do not call the API twice.
  4. Aggregates the logs to one row per player + team and prints quality checks.

Why game logs and not season totals? The season-totals endpoint returns one row
per player, so a player traded in the middle of the season has ALL his minutes
counted for one team. Game logs know the team of every single game.

Run it from the project root folder:
    python -m src.extract_stats
"""

import json
import logging
import time

import pandas as pd
from nba_api.stats.endpoints import leaguedashplayerstats, playergamelogs

import config
from src import transform

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


def fetch_raw_cached(cache_file, make_call) -> dict:
    """
    Generic "cache first" download used by every endpoint.

    1. If cache_file exists, read it and do NOT call the API.
    2. Otherwise run make_call() (with retries), save the raw JSON text to
       cache_file and return it as a dictionary.
    """
    if cache_file.exists():
        log.info("Reading from cache: %s", cache_file.name)
        return json.loads(cache_file.read_text(encoding="utf-8"))

    log.info("Calling nba_api, will save to %s ...", cache_file.name)
    endpoint = call_with_retry(make_call)
    raw_json = endpoint.get_json()  # raw JSON text, exactly as the server sent it

    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(raw_json, encoding="utf-8")
    log.info("Saved to: %s", cache_file)

    time.sleep(config.CALL_PAUSE)  # be polite to the server
    return json.loads(raw_json)


def fetch_player_stats_raw(season: str) -> dict:
    """Season TOTALS per player (one row per player). We use it as a cross-check."""
    return fetch_raw_cached(
        config.RAW_DIR / f"player_base_{season}.json",
        lambda: leaguedashplayerstats.LeagueDashPlayerStats(
            season=season,
            season_type_all_star=config.SEASON_TYPE,
            per_mode_detailed="Totals",            # season totals (not per game)
            measure_type_detailed_defense="Base",  # basic stats (points, minutes...)
            timeout=config.REQUEST_TIMEOUT,
        ),
    )


def fetch_game_logs_raw(season: str) -> dict:
    """GAME-BY-GAME logs: one row per player per game, with the team of that game."""
    return fetch_raw_cached(
        config.RAW_DIR / f"player_gamelogs_{season}.json",
        lambda: playergamelogs.PlayerGameLogs(
            season_nullable=season,
            season_type_nullable=config.SEASON_TYPE,
            timeout=config.REQUEST_TIMEOUT,
        ),
    )


def raw_to_dataframe(raw: dict) -> pd.DataFrame:
    """
    Turns a raw response into a DataFrame.

    The nba_api response looks roughly like this:
      {"resultSets": [{"name": "...",
                       "headers": ["PLAYER_ID", "PLAYER_NAME", ...],
                       "rowSet":  [[203999, "Nikola Jokic", ...], ...]}]}
    So: headers = column names, rowSet = rows.
    """
    result_set = raw["resultSets"][0]
    return pd.DataFrame(result_set["rowSet"], columns=result_set["headers"])


def main():
    # --- 1. Extract ----------------------------------------------------------
    logs = raw_to_dataframe(fetch_game_logs_raw(config.SEASON))
    totals = raw_to_dataframe(fetch_player_stats_raw(config.SEASON))

    print("\n=== GAME LOGS OVERVIEW ===")
    print(f"Season: {config.SEASON}")
    print(f"Rows (player-games): {len(logs)}")
    print(f"Distinct games: {logs['GAME_ID'].nunique()}")
    print(f"Distinct teams: {logs['TEAM_ABBREVIATION'].nunique()}")
    print(f"Rows with missing MIN: {pd.to_numeric(logs['MIN'], errors='coerce').isna().sum()}")

    # --- 2. Aggregate to one row per player + team ---------------------------
    player_team = transform.aggregate_player_team(logs, config.SEASON)
    print("\n=== PLAYER + TEAM TABLE ===")
    print(f"Rows (player + team): {len(player_team)}")
    print(f"Distinct players: {player_team['PLAYER_ID'].nunique()}")

    # Players with more than one team in the season = traded players.
    teams_per_player = player_team.groupby("PLAYER_ID")["TEAM_ID"].nunique()
    traded_ids = teams_per_player[teams_per_player > 1].index
    print(f"Players who played for 2+ teams: {len(traded_ids)}")
    examples = (
        player_team[player_team["PLAYER_ID"].isin(traded_ids)]
        .sort_values(["PLAYER_NAME", "MIN"], ascending=[True, False])
        .head(6)
    )
    print("Examples (one row per team):")
    print(examples[["PLAYER_NAME", "TEAM_ABBREVIATION", "GP", "MIN"]].round(0).to_string(index=False))

    # --- 3. Quality checks ---------------------------------------------------
    # Check A: team minutes. A team plays 82 games x 240 min = 19,680 (a bit more
    # with overtime), so every team should now be close to that number.
    team_minutes = player_team.groupby("TEAM_ABBREVIATION")["MIN"].sum().round(0).astype(int)
    team_minutes = team_minutes.sort_values()
    print("\n=== CHECK A: total minutes per team (expected about 19,680) ===")
    print("Lowest 3:")
    print(team_minutes.head(3).to_string())
    print("Highest 3:")
    print(team_minutes.tail(3).to_string())

    # Check B: cross-check with the season-totals source. For every player, the
    # minutes summed over all his teams must match the totals endpoint.
    mine = player_team.groupby("PLAYER_ID")["MIN"].sum()
    theirs = totals.set_index("PLAYER_ID")["MIN"]
    both = pd.concat([mine.rename("from_logs"), theirs.rename("from_totals")], axis=1).dropna()
    diff = (both["from_logs"] - both["from_totals"]).abs()
    print("\n=== CHECK B: game logs vs season totals ===")
    print(f"Players compared: {len(both)}")
    print(f"Biggest difference in minutes: {diff.max():.1f}")
    print(f"Players with a difference above 5 minutes: {(diff > 5).sum()}")

    # --- 4. Top N per team + Minnesota case study ----------------------------
    n = config.TOP_N_PLAYERS_PER_TEAM
    top = transform.select_top_players(player_team, n)
    print(f"\n=== TOP {n} BY MINUTES PER TEAM ===")
    print(f"Rows: {len(top)} (expected {30 * n})")
    print(f"Teams: {top['TEAM_ABBREVIATION'].nunique()}")

    # MPG = minutes per game = total minutes / games played (for that team).
    mn = top[top["TEAM_ABBREVIATION"] == "MIN"].copy()
    mn["MPG"] = (mn["MIN"] / mn["GP"]).round(1)
    mn["MIN"] = mn["MIN"].round(0).astype(int)
    print("\nMinnesota top players:")
    print(mn[["PLAYER_NAME", "GP", "MIN", "MPG"]].to_string(index=False))


if __name__ == "__main__":
    main()