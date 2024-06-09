import os
from datetime import datetime

import pandas as pd
import streamlit as st

ss = st.session_state
COLUMNS = ["Name", f"TeamA", f"TeamB", f"ScoreA", "ScoreB", f"Factor"]
DTYPES = {"Name": str, f"TeamA": str, f"TeamB": str, f"ScoreA": int, "ScoreB": int, f"Factor": int}
INDEX_COLUMNS = ["Name", f"TeamA", f"TeamB"]
DEV_FLAG = True


def load_data(date_str):
    filepath = f"data/tips/{date_str}.csv"
    if os.path.exists(filepath):
        return pd.read_csv(filepath, dtype=DTYPES).set_index(INDEX_COLUMNS)
    else:
        return pd.DataFrame(columns=COLUMNS).set_index(INDEX_COLUMNS)


def save_data(date_str, df):
    filepath = f"data/tips/{date_str}.csv"
    df.to_csv(filepath, index=True)


def get_now():
    if DEV_FLAG:
        return datetime.combine(ss["dev_date"], ss["dev_time"])

    return datetime.now()
