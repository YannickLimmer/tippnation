import pandas as pd
import streamlit as st
from util import ss, load_data


def display_entries():

    unique_dates = [s.strftime('%d-%b') for s in ss["schedule"].Datetime.dt.date.unique()]
    dates = st.multiselect("Choose dates to display", unique_dates)
    if dates:
        df = pd.concat([load_data(d) for d in dates], axis=0)
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
            },
        )
        # cols = st.columns(len(df.columns) + 1)
        # for col, df_col in zip(cols[1:], df.columns):
        #     st.table(df[col])
    # st.dataframe(ss["schedule"])
