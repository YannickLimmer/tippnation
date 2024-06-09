import pandas as pd
import streamlit as st

from util import ss, load_data, INDEX_COLUMNS, ROOT, get_now


def compute_points(schedule, types):
    dates = [s.strftime('%d-%b') for s in ss["schedule"].Datetime.dt.date.unique()]
    dfs = [
        pd.merge(
            load_data(d).reset_index(),
            schedule[schedule.Datetime.dt.date.apply(lambda s: s.strftime('%d-%b')) == d],
            on=["TeamA", "TeamB"],
        ) for d in dates
    ]
    df = pd.concat(dfs, axis=0)
    df["Favorite"] = df["Name"].apply(lambda k: ss["user_info"][k].get("Favorite"))
    df = df[~(pd.isna(df["ScoreA"]) | pd.isna(df["ScoreB"]) | pd.isna(df["ResultA"]) | pd.isna(df["ResultB"]))]
    df["Base"] = compute_base(df)
    df["FBase"] = df["Base"] * df["Factor"]
    df['Best'] = compute_best(df, types)
    df['Fav'] = compute_fav(df, types)
    df['Final'] = df.FBase + df.Best + df.Fav
    df.to_csv(ROOT + "/data/Points.csv", index=False)


def compute_base(df):
    base = (
                   (
                           (df["ResultA"] > df["ResultB"]) & (df["ScoreA"] > df["ScoreB"])
                   ) | (
                           (df["ResultA"] == df["ResultB"]) & (df["ScoreA"] == df["ScoreB"])
                   ) | (
                           (df["ResultA"] < df["ResultB"]) & (df["ScoreA"] < df["ScoreB"])
                   )
           ).astype(int) * 2
    base += (
                    (df["ResultA"] != df["ResultB"]) & (df["ScoreA"] - df["ScoreB"] == df["ResultA"] - df["ResultB"])
            ).astype(int) * 1
    base += ((df["ScoreA"] == df["ResultA"]) & (df["ScoreB"] == df["ResultB"])).astype(int) * 2
    base += (
                    (df["ResultA"] == df["ResultB"]) & (df["ScoreA"] == df["ResultA"]) & (df["ScoreB"] == df["ResultB"])
            ).astype(int) * 1
    return base


def compute_best(df, types):
    by_match = df.groupby(['TeamA', 'TeamB', 'Datetime'])['Base']
    is_unique_max = by_match.transform(lambda x: x[x == x.max()].count() == 1)
    return ((df['Base'] == by_match.transform('max')) & is_unique_max) * df["Type"].apply(lambda s: types[s]["Best"])


def compute_fav(df, types):
    w = df["Type"].apply(lambda s: types[s]["Favorite"])
    return (df["Favorite"] == df["TeamA"]) * (
        w * (df["ResultA"] > df["ResultB"]) + 2 * (df["ResultA"] == df["ResultB"]) - 4 * (df["ResultA"] < df["ResultB"])
    ) + (df["Favorite"] == df["TeamB"]) * (
        w * (df["ResultA"] < df["ResultB"]) + 2 * (df["ResultA"] == df["ResultB"]) - 4 * (df["ResultA"] > df["ResultB"])
    )


