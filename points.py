import numpy as np
import pandas as pd
import streamlit as st

from util import ss, load_data, INDEX_COLUMNS, ROOT, get_now


def compute_and_save_points(schedule):
    df = collect_complete_match_data(schedule)
    st.dataframe(df)
    df = compute_points(df)
    st.dataframe(df)
    df.to_csv(ROOT + "/data/Points.csv", index=False)


def compute_points(df):
    types = ss["Types"]
    df["Favorite"] = df.Name.apply(lambda k: ss["user_info"][k].get("Favorite"))
    df = df[~(pd.isna(df.ScoreA) | pd.isna(df.ScoreB) | pd.isna(df.ResultA) | pd.isna(df.ResultB))]
    df["ScoreDiff"] = df.ScoreA - df.ScoreB
    df["ResultDiff"] = df.ResultA - df.ResultB
    df["Base"] = compute_base(df)
    df["FBase"] = df.Base * df.Factor
    df['Exotic'] = compute_exotic(df, types)
    df['Fav'] = compute_fav(df, types)
    df['Final'] = df.FBase + df.Exotic + df.Fav
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
    df = pd.concat(dfs, axis=0)
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
           ) * 2
    base += ((df["ResultA"] != df["ResultB"]) & (df.ScoreDiff == df.ResultDiff)) * 1
    base += ((df["ScoreA"] == df["ResultA"]) & (df["ScoreB"] == df["ResultB"])) * 2
    base += ((df["ResultA"] == df["ResultB"]) & (df["ScoreA"] == df["ResultA"]) & (df["ScoreB"] == df["ResultB"])) * 1
    return base


def compute_exotic(df, types):
    by_match = df.groupby(['TeamA', 'TeamB', 'Datetime'])
    df = df.reset_index()
    df = df.set_index(['TeamA', 'TeamB', 'Datetime'])
    df["AvScoreDiff"] = by_match.ScoreA.mean() - by_match.ScoreB.mean()
    df = df.reset_index()
    df = df.set_index("index")
    df["Exotic"] = np.maximum(np.abs(df.AvScoreDiff - df.ResultDiff) - np.abs(df.ResultDiff - df.ScoreDiff), 0).astype(int)
    return df["Exotic"]


def compute_fav(df, types):
    w = df["Type"].apply(lambda s: types[s]["Favorite"])
    return (df["Favorite"] == df["TeamA"]) * (
        w * (df["ResultA"] > df["ResultB"]) + 2 * (df["ResultA"] == df["ResultB"]) - 4 * (df["ResultA"] < df["ResultB"])
    ) + (df["Favorite"] == df["TeamB"]) * (
        w * (df["ResultA"] < df["ResultB"]) + 2 * (df["ResultA"] == df["ResultB"]) - 4 * (df["ResultA"] > df["ResultB"])
    )


