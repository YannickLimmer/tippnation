import os
from datetime import datetime

import pandas as pd
import streamlit as st

ss = st.session_state
COLUMNS = ["Name", f"TeamA", f"TeamB", f"ScoreA", "ScoreB", f"Factor"]
INDEX_COLUMNS = ["Name", f"TeamA", f"TeamB"]
DEV_FLAG = True


def load_data(filepath):
    if os.path.exists(filepath):
        return pd.read_csv(filepath).set_index(INDEX_COLUMNS)
    else:
        return pd.DataFrame(columns=COLUMNS).set_index(INDEX_COLUMNS)


def save_data(filepath, df):
    df.to_csv(filepath, index=True)


def get_now():
    if DEV_FLAG:
        return datetime.combine(ss["dev_date"], ss["dev_time"])

    return datetime.now()
