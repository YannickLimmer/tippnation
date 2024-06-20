import numpy as np
import pandas as pd
import streamlit as st

from util import ROOT, SNS_COLORS


def display_points():
    try:
        df_raw = pd.read_csv(ROOT + '/data/Points.csv')
        df_raw["Datetime"] = pd.to_datetime(df_raw["Datetime"])
    except FileNotFoundError:
        return
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
    st.dataframe(df.reset_index().set_index(["Team A", "Team B"]), column_config={
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

    st.markdown("### Standings")
    standings = df_raw[["Name", "Base", "FBase", "Exotic", "Fav", "KW", "Final"]]
    standings = standings.rename({"Base": "Raw", "FBase": "Base", "Fav": "Favorite", "KW": "Kanonenwilli"}, axis=1)
    standings = standings.groupby("Name").sum().sort_values("Final", ascending=False).reset_index()
    standings["Rank"] = standings["Final"].rank(method='min', ascending=False).astype(int)
    standings = standings[["Name", "Rank", "Raw", "Base", "Exotic", "Favorite", "Kanonenwilli", "Final"]].set_index("Name")
    st.dataframe(standings.style.applymap(lambda x: f"background-color: {SNS_COLORS[0]}", subset="Final"), hide_index=False)

    st.markdown("### Points Progression")
    st.line_chart(df.reset_index()[[k for k in df.columns if "Sum" in k]].rename({k: k[:-4] for k in df.columns}, axis=1))

    with st.expander("Base Progression"):
        df = df_raw.rename({"TeamA": "Team A", "TeamB": "Team B", "ResultA": "Result A", "ResultB": "Result B"}, axis=1)
        df = df.set_index(["Datetime", "Team A", "Team B", "Result A", "Result B", "Name"])
        df.Final -= df.KW
        df = df[["FBase"]]
        df = df.unstack('Name')
        max_points = int(np.ceil(df.fillna(0).values.max()))
        cols = df.columns.values
        df.columns = [col[-1] + " Points" for col in cols]
        df = df.sort_index()
        for col in cols:
            df[col[-1] + " Sum"] = df[col[-1] + " Points"].cumsum()
        df = df[[v for col in cols for v in [col[-1] + " Points", col[-1] + " Sum"]]]
        st.line_chart(df.reset_index()[[k for k in df.columns if "Sum" in k]].rename({k: k[:-4] for k in df.columns}, axis=1))

    with st.expander("Progression without Kanonenwilli"):
        df = df_raw.rename({"TeamA": "Team A", "TeamB": "Team B", "ResultA": "Result A", "ResultB": "Result B"}, axis=1)
        df = df.set_index(["Datetime", "Team A", "Team B", "Result A", "Result B", "Name"])
        df.Final -= df.KW
        df = df[["Final"]]
        df = df.unstack('Name')
        max_points = int(np.ceil(df.fillna(0).values.max()))
        cols = df.columns.values
        df.columns = [col[-1] + " Points" for col in cols]
        df = df.sort_index()
        for col in cols:
            df[col[-1] + " Sum"] = df[col[-1] + " Points"].cumsum()
        df = df[[v for col in cols for v in [col[-1] + " Points", col[-1] + " Sum"]]]
        st.line_chart(df.reset_index()[[k for k in df.columns if "Sum" in k]].rename({k: k[:-4] for k in df.columns}, axis=1))

    st.markdown("### Point Composition")
    dcols = st.columns(4)
    with dcols[0]:
        date = st.date_input("Choose Date")
    detailed = df_raw[df_raw["Datetime"].dt.date == date][["Name", "Datetime", "TeamA", "TeamB", "FBase", "Exotic", "Fav", "KW"]]
    detailed = detailed.rename({"FBase": "Base", "Exotic": "Exotic Bonus", "Fav": "Favorite Bonus", "KW": "Kanonenwilli"}, axis=1)
    dcols = st.columns(4)
    for dcol, ((d, n1, n2), g) in zip(dcols, detailed.groupby(["Datetime", "TeamA", "TeamB"])):
        with dcol:
            st.write(f"{n1} vs {n2}")
            st.bar_chart(g.drop(["Datetime", "TeamA", "TeamB"], axis=1).groupby("Name").sum())
