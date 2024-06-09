import pandas as pd
import streamlit as st
from util import ss, load_data, INDEX_COLUMNS, get_now


def display_entries():
    schedule = ss["schedule"]
    unique_dates = [s.strftime('%d-%b') for s in ss["schedule"].Datetime.dt.date.unique()]
    dates = st.multiselect("Choose dates to display", unique_dates)
    if dates:
        dfs = [
            pd.merge(
                load_data(d).reset_index(),
                schedule[schedule.Datetime.dt.date.apply(lambda s: s.strftime('%d-%b')) == d],
                on=["TeamA", "TeamB"],
            ).set_index(["Datetime"] + INDEX_COLUMNS) for d in dates
        ]
        df = pd.concat(dfs, axis=0)
        df = df.loc[(df.reset_index().Datetime < get_now()).values, :]
        df = df.rename({"ScoreA": "A", "ScoreB": "B", "Factor": "X"}, axis=1)
        df = df.unstack('Name').fillna(0)
        df.columns = df.columns.swaplevel(0, 1)
        df = df.sort_index(axis=1, level=0).astype(int)
        df.columns = [' '.join(col).strip() for col in df.columns.values]
        st.dataframe(df, column_config={
                k: st.column_config.ProgressColumn(
                    k,
                    help="The factor applied to this game",
                    format="%f",
                    min_value=0,
                    max_value=10,
                    width="small",
                ) for k in df.columns if "X" in k
            } | {
                "Datetime": st.column_config.DateColumn("Date", format="DD-MMM, HH:mm")
            },
        )
