import json

import streamlit as st
import pandas as pd

from admin import modify_schedule
from display_entries import display_entries
from make_entries import make_entries
from util import ss, DEV_FLAG


def main():
    for key, value in ss.items():
        ss[key] = value

    st.set_page_config(layout="wide")

    ss["schedule"] = pd.read_csv("data/Schedule.csv", index_col="Index")
    ss["schedule"]["Datetime"] = pd.to_datetime(ss["schedule"]["Datetime"])

    with open("data/Players.json", "r") as fp:
        ss["user_info"] = json.load(fp)

    if DEV_FLAG:
        with st.container(border=True):
            cols = st.columns(4)
            with cols[0]:
                st.date_input("Developer: Date", key="dev_date")
            with cols[1]:
                st.time_input("Developer: Time", key="dev_time")

    tabs = st.tabs(["Enter Scores", "View Entries", "Heatmaps", "View Points", "View Ranking", "Admin"])
    with tabs[0]:
        make_entries()
    with tabs[1]:
        display_entries()
    with tabs[-1]:
        modify_schedule()


if __name__ == "__main__":
    main()
