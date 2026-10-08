"""
transform.py: cleaning and reshaping of the raw data.

Right now it holds two functions:
  - aggregate_player_team: game-by-game rows -> one row per player AND team
  - select_top_players:    keep the top n players by minutes inside each team
"""

import pandas as pd


def aggregate_player_team(game_logs: pd.DataFrame, season: str) -> pd.DataFrame:
    """
    Turns game logs (one row = one player in one game) into one row per
    player + team. This is the "grain" of the table from the project plan:
    a player traded in the middle of the season gets TWO rows, one per team,
    and each row only counts the games and minutes played for that team.

    Example (made-up numbers):
        game logs:   Player A, team X, 30 min      ->   Player A, team X, GP 2, MIN 60
                     Player A, team X, 30 min
                     Player A, team Y, 20 min      ->   Player A, team Y, GP 1, MIN 20
    """
    df = game_logs.copy()

    # Minutes should already be numbers; to_numeric turns anything odd into NaN
    # instead of crashing, so we can count the bad rows afterwards.
    df["MIN"] = pd.to_numeric(df["MIN"], errors="coerce")

    grouped = df.groupby(["PLAYER_ID", "TEAM_ID"], as_index=False).agg(
        PLAYER_NAME=("PLAYER_NAME", "first"),
        TEAM_ABBREVIATION=("TEAM_ABBREVIATION", "first"),
        GP=("GAME_ID", "nunique"),   # number of different games played
        MIN=("MIN", "sum"),          # total minutes (NaN rows are skipped)
    )
    grouped.insert(0, "SEASON", season)
    return grouped


def select_top_players(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """
    Keeps the top n players by total minutes (MIN) inside each team.

    Steps (think of ranking players on every team's roster):
      1. sort by team, then by minutes from highest to lowest
      2. groupby("TEAM_ABBREVIATION").head(n) takes the first n rows of each team
    With 30 teams and n = 8 we expect 240 rows.
    """
    ranked = df.sort_values(["TEAM_ABBREVIATION", "MIN"], ascending=[True, False])
    return ranked.groupby("TEAM_ABBREVIATION").head(n).reset_index(drop=True)
