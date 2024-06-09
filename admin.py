import json

import streamlit as st

from points import compute_points
from util import ss, ROOT


def modify_schedule():
    schedule = st.data_editor(ss["schedule"], hide_index=True, num_rows="dynamic", column_config={
                "Datetime": st.column_config.DateColumn("Date", format="DD-MMM, HH:mm")
    })
    cols = st.columns(4)
    with cols[0]:
        pwd = st.text_input("Enter Admin Password", type="password")
    with cols[1]:
        button = st.button("Save and Compute Points")
    if button:
        if pwd == st.secrets["Admin"]["Password"]:
            schedule.to_csv(ROOT + "/data/Schedule.csv")
            st.success("Changes have been saved successfully!")
            compute_points(schedule, ss["Types"])
            st.success("Computation of points completed!")
        else:
            st.warning("Password is incorrect.")
