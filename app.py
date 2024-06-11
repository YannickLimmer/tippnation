import json

import streamlit as st
import pandas as pd

from admin import modify_schedule
from display_entries import display_entries
from display_points import display_points
from heat_map import heat_maps
from make_entries import make_entries
from util import ss, DEV_FLAG, ROOT, get_now


def main():
    for key, value in ss.items():
        ss[key] = value

    st.set_page_config(layout="wide")

    ss["schedule"] = pd.read_csv(ROOT + "/data/Schedule.csv", index_col="Index")
    ss["schedule"]["Datetime"] = pd.to_datetime(ss["schedule"]["Datetime"])

    with open(ROOT + "/data/Players.json", "r") as fp:
        ss["user_info"] = json.load(fp)

    with open(ROOT + "/data/Admin.json", "r") as fp:
        ss["Types"] = json.load(fp)["Types"]

    if DEV_FLAG:
        with st.container(border=True):
            cols = st.columns(4)
            with cols[0]:
                st.date_input("Developer: Date", key="dev_date")
            with cols[1]:
                st.time_input("Developer: Time", key="dev_time")

    # st.markdown(f"""<div style="text-align: right;"> Time now: {get_now().strftime("%H:%m")} </div> """, unsafe_allow_html=True)
    tabs = st.tabs(["Enter Scores", "View Entries", "Heatmaps", "Points and Ranking", "Admin"])
    with tabs[0]:
        make_entries()
    with tabs[1]:
        display_entries()
    with tabs[2]:
        st.warning("Coming soon!")
        heat_maps()
    with tabs[3]:
        display_points()
    with tabs[-1]:
        modify_schedule()


if __name__ == "__main__":
    main()
