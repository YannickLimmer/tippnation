import numpy as np
import pandas as pd
import streamlit as st
from util import ss, load_data, INDEX_COLUMNS, get_now, country_name_to_flag


def display_entries():
    st.markdown("### Favorites")
    st.dataframe(pd.DataFrame([{k: v["Favorite"] for k, v in ss["user_info"].items()}]), hide_index=True)
    st.markdown("### Entries")
    schedule = ss["schedule"]
    unique_dates = [s.strftime('%d-%b') for s in ss["schedule"].Datetime.dt.date.unique()]
    dates = st.multiselect("Choose dates to display", unique_dates)
    all_names = list(ss["user_info"].keys())
    names = st.multiselect("Choose players to display", options=all_names, default=all_names)
    if dates and names:
        dfs = [
            pd.merge(
                load_data(d).reset_index(),
                schedule[schedule.Datetime.dt.date.apply(lambda s: s.strftime('%d-%b')) == d],
                on=["TeamA", "TeamB"],
            ).set_index(["Datetime", "Type", "ResultA", "ResultB"] + INDEX_COLUMNS) for d in dates
        ]
        df = pd.concat(dfs, axis=0)
        if df.empty:
            return
        max_factor = int(np.ceil(df["Factor"].values.max()))

        if False:
            df = df.reset_index()
            df["TeamA"] = df["TeamA"].apply(country_name_to_flag)
            df["TeamB"] = df["TeamB"].apply(country_name_to_flag)
            df = df.set_index(["Datetime", "Type", "ResultA", "ResultB"] + INDEX_COLUMNS)

        df = df.loc[(df.reset_index().Datetime < get_now()).values, :]
        df = df.loc[df.reset_index().Name.isin(names).values, :]

        # Display
        df = df.rename({"ScoreA": "A", "ScoreB": "B", "Factor": "X"}, axis=1)
        df = df.unstack('Name')
        for col in df.columns:
            if "X" in col:
                df[col] = df[col].fillna(0)
        df.columns = df.columns.swaplevel(0, 1)
        df = df.sort_index(axis=1, level=0)  # .astype(int)
        df.columns = [' '.join(col).strip() for col in df.columns.values]
        df = df.reset_index().set_index(["TeamA", "TeamB"])
        st.dataframe(df, column_config={
                k: st.column_config.ProgressColumn(
                    k,
                    help="The factor applied to this game",
                    format="%f",
                    min_value=0,
                    max_value=max_factor,
                    width="small",
                ) for k in df.columns if "X" in k
            } | {
                "Datetime": st.column_config.DateColumn("Date", format="DD-MMM, HH:mm")
            } | {
                "TeamB": st.column_config.TextColumn("B")
            } | {
                "TeamA": st.column_config.TextColumn("A")
            },
        )
