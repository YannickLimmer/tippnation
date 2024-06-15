import numpy as np
import pandas as pd
import streamlit as st

from util import ss, load_data, INDEX_COLUMNS, ROOT, get_now, save_data

TO_RANK = [8, 7, 6, 5, 4]
PROBABILITIES = [0.1, 0.2, 0.4, 0.2, 0.1]


def gets_rocket(last):
    if last == 1:
        return np.random.binomial(1, 2/3)
    if last == 2:
        return np.random.binomial(1, 1/2)
    if last == 3:
        return np.random.binomial(1, 1/3)
    if last == 4:
        return np.random.binomial(1, 1/5)
    return 0


def gets_rocket_to(last):
    if gets_rocket(last):
        return np.random.choice(TO_RANK, p=PROBABILITIES)
    else:
        return None


def compute_and_save_points(schedule):
    df = collect_complete_match_data(schedule).sort_values("Datetime")
    st.dataframe(df)
    df = df.set_index(["Datetime", "TeamA", "TeamB"])
    willi_flag = ~pd.isna(df["Kanonenwilli"])
    df_with_willi = df[willi_flag]
    df_without_willi = df[~willi_flag]
    while (not df_without_willi.empty) and all(~pd.isna(df_with_willi.ResultA) & ~ pd.isna(df_with_willi.ResultB)):
        if len(df_without_willi.Name.unique()) < 11:
            break

        # Find next game data
        grouped_by_game = df_without_willi.groupby(["Datetime", "TeamA", "TeamB"])
        next_game = grouped_by_game.get_group((list(grouped_by_game.groups)[0]))

        # Compute willi bonus
        points_with_willi = compute_points(df_with_willi).groupby("Name")[["Final"]].sum()
        points_with_willi = points_with_willi.sort_values("Final", ascending=False)
        points_with_willi["Last"] = points_with_willi.rank(method='min', ascending=True)
        points_with_willi["GetsToRank"] = points_with_willi.Last.apply(gets_rocket_to)

        def calculate_difference(row):
            if pd.notna(row['GetsToRank']):
                target_index = int(row['GetsToRank'] - 1)
                return max(points_with_willi.iloc[target_index]['Final'] - row['Final'], 0)
            else:
                return 0
        points_with_willi["Kanonenwilli"] = points_with_willi.apply(calculate_difference, axis=1)

        # Add to df
        if points_with_willi.empty:
            df.loc[next_game.index, "Kanonenwilli"] = 0
        else:
            df.loc[next_game.index, "Kanonenwilli"] = points_with_willi.loc[df.loc[next_game.index, "Name"], "Kanonenwilli"].values

        # Save to tips
        next_game = next_game.reset_index()
        date_str = next_game.iloc[0]["Datetime"].strftime('%d-%b')
        tips = load_data(date_str)
        tips_ = (slice(None), next_game.reset_index().iloc[0].TeamA, next_game.reset_index().iloc[0].TeamB)
        if points_with_willi.empty:
            tips.loc[tips_, "Kanonenwilli"] = 0
        else:
            tips.loc[tips_, "Kanonenwilli"] = points_with_willi.loc[tips.loc[tips_, :].reset_index().Name, "Kanonenwilli"].values
        save_data(date_str, tips)

        # Update last game
        willi_flag = ~pd.isna(df["Kanonenwilli"])
        df_with_willi = df[willi_flag]
        df_without_willi = df[~willi_flag]

    df = compute_points(df)
    st.dataframe(df)
    df.to_csv(ROOT + "/data/Points.csv", index=True)



def compute_points(df):
    types = ss["Types"]
    df["Favorite"] = df.Name.apply(lambda k: ss["user_info"][k].get("Favorite"))
    df = df[~(pd.isna(df.ScoreA) | pd.isna(df.ScoreB) | pd.isna(df.ResultA) | pd.isna(df.ResultB))]
    df["ScoreDiff"] = df.ScoreA - df.ScoreB
    df["ResultDiff"] = df.ResultA - df.ResultB
    df["ScoreDist"] = np.abs(df.ScoreA - df.ResultA) + np.abs(df.ScoreB - df.ResultB)
    df["Base"] = compute_base(df)
    df["FBase"] = df.Base * df.Factor + df["Type"].apply(lambda s: types[s]["MaxFactor"])
    df['Exotic'] = compute_exotic(df, types)
    df['Fav'] = compute_fav(df, types)
    df['KW'] = compute_kanonenwilli(df)
    df['Final'] = df.FBase + df.Exotic + df.Fav + df.KW
    return df


def collect_complete_match_data(schedule):
    dates = [s.strftime('%d-%b') for s in ss["schedule"].Datetime.dt.date.unique()]
    dfs = [
        pd.merge(
            load_data(d).reset_index(),
            schedule[schedule.Datetime.dt.date.apply(lambda s: s.strftime('%d-%b')) == d],
            on=["TeamA", "TeamB"],
        ) for d in dates
    ]
    df = pd.concat(dfs, axis=0).reset_index(drop=True)
    return df


def compute_base(df):
    base = (
                   (
                           (df["ResultA"] > df["ResultB"]) & (df["ScoreA"] > df["ScoreB"])
                   ) | (
                           (df["ResultA"] == df["ResultB"]) & (df["ScoreA"] == df["ScoreB"])
                   ) | (
                           (df["ResultA"] < df["ResultB"]) & (df["ScoreA"] < df["ScoreB"])
                   )
           ) * 2 - 1
    base += ((np.abs(df["ResultA"] - df["ScoreA"]) + np.abs(df.ResultB - df.ScoreB)) <= 1) * 1
    base += ((df["ResultA"] != df["ResultB"]) & (df.ScoreDiff == df.ResultDiff)) * 1
    base += ((df["ScoreA"] == df["ResultA"]) & (df["ScoreB"] == df["ResultB"])) * 2
    base += ((df["ResultA"] == df["ResultB"]) & (df["ScoreA"] == df["ResultA"]) & (df["ScoreB"] == df["ResultB"])) * 1
    return base


def compute_exotic(df, types):
    w = df["Type"].apply(lambda s: types[s]["Exotic"])
    by_match = df.groupby(['Datetime', 'TeamA', 'TeamB'])
    df["AvScoreDiff"] = by_match.ScoreDiff.mean()
    df["AvScoreDist"] = by_match.ScoreDist.mean()
    df["Exotic"] = (
            w * (
                np.maximum(np.abs(df.AvScoreDiff - df.ResultDiff) - np.abs(df.ResultDiff - df.ScoreDiff), 0) +
                np.maximum(df.AvScoreDist - df.ScoreDist, 0)
            ) / 2
    ).astype(int)
    return df["Exotic"].astype(int)


def compute_fav(df, types):
    w = df["Type"].apply(lambda s: types[s]["Favorite"])
    return (df["Favorite"] == df.reset_index()["TeamA"].values) * (
        w * (df["ResultA"] > df["ResultB"]) + 3 * (df["ResultA"] == df["ResultB"]) - 6 * (df["ResultA"] < df["ResultB"])
    ) + (df["Favorite"] == df.reset_index()["TeamB"].values) * (
        w * (df["ResultA"] < df["ResultB"]) + 3 * (df["ResultA"] == df["ResultB"]) - 6 * (df["ResultA"] > df["ResultB"])
    )


def compute_kanonenwilli(df):
    return df["Kanonenwilli"] * ((
            (df["ResultA"] > df["ResultB"]) & (df["ScoreA"] > df["ScoreB"])
    ) | (
            (df["ResultA"] == df["ResultB"]) & (df["ScoreA"] == df["ScoreB"])
    ) | (
            (df["ResultA"] < df["ResultB"]) & (df["ScoreA"] < df["ScoreB"])
    ))


