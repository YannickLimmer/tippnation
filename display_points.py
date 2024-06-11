import numpy as np
import pandas as pd
import streamlit as st

from util import ROOT


def display_points():
    df_raw = pd.read_csv(ROOT + '/data/Points.csv')
    df_raw["Datetime"] = pd.to_datetime(df_raw["Datetime"])
    if df_raw.empty:
        return
    df = df_raw.rename({"TeamA": "Team A", "TeamB": "Team B", "ResultA": "Result A", "ResultB": "Result B"}, axis=1)
    df = df.set_index(["Datetime", "Team A", "Team B", "Result A", "Result B", "Name"])
    df = df[["Final"]]
    df = df.unstack('Name')
    max_points = int(np.ceil(df.fillna(0).values.max()))
    cols = df.columns.values
    df.columns = [col[-1] + " Points" for col in cols]
    df = df.sort_index()
    for col in cols:
        df[col[-1] + " Sum"] = df[col[-1] + " Points"].cumsum()
    df = df[[v for col in cols for v in [col[-1] + " Points", col[-1] + " Sum"]]]

    st.markdown("### Points by Match")
    st.dataframe(df, column_config={
        "Datetime": st.column_config.DateColumn("Date", format="DD-MMM, HH:mm")
    } | {
        k: st.column_config.ProgressColumn(
            k,
            help="Points obtained for this match",
            format="%f",
            min_value=0,
            max_value=max_points,
            width="small",
        ) for k in df.columns if "Points" in k
    })

    st.markdown("### Points Progression")
    st.line_chart(df.reset_index()[[k for k in df.columns if "Sum" in k]].rename({k: k[:-4] for k in df.columns}, axis=1))

    st.markdown("### Standings")
    with st.container():
        standings = df.reset_index()[[k for k in df.columns if "Sum" in k]].iloc[-1].T
        standings = standings.rename({k: k[:-4] for k in df.columns})
        standings = standings.sort_values(ascending=False).reset_index()
        standings["Rank"] = standings.index + 1
        standings = standings.set_index("Rank").rename(
            {"index": "Name"}, axis=1
        )
        standings = standings.rename(
            {standings.columns[-1]: "Points"}, axis=1
        )
        st.dataframe(standings)

    st.markdown("### Point Composition")
    dcols = st.columns(4)
    with dcols[0]:
        date = st.date_input("Choose Date")
    detailed = df_raw[df_raw["Datetime"].dt.date == date][["Name", "TeamA", "TeamB", "FBase", "Exotic", "Fav"]]
    detailed = detailed.rename({"FBase": "Base", "Exotic": "Exotic Bonus", "Fav": "Favorite"}, axis=1)
    dcols = st.columns(4)
    for dcol, ((n1, n2), g) in zip(dcols, detailed.groupby(["TeamA", "TeamB"])):
        with dcol:
            st.write(f"{n1} vs {n2}")
            st.bar_chart(g.drop(["TeamA", "TeamB"], axis=1).groupby("Name").sum())
