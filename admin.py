import logging

import numpy as np
import streamlit as st

from points import compute_points
from util import ss, ROOT, get_now, load_data, save_data
from streamlit import logger

# Parameters
LAMBDA_A = 1.2
LAMBDA_B = 1.2
LAMBDA_AB = 0.1


def simulate_outcome():
    n = np.random.poisson(LAMBDA_AB)
    x = np.random.poisson(LAMBDA_A) + n
    y = np.random.poisson(LAMBDA_B) + n
    return x, y


def fill_missing(schedule, types):
    for i, row in schedule[(schedule.Datetime < get_now()).values].iterrows():
        df = load_data(row["Datetime"].strftime('%d-%b'))
        for name in ss["user_info"].keys():
            if (name, row["TeamA"], row["TeamB"]) not in df.index:
                logging.info(f"Fill in data for {name, row['TeamA'], row['TeamB']} at date {row['Datetime'].strftime('%d-%b')}")
                x, y = simulate_outcome()
                df.loc[(name, row["TeamA"], row["TeamB"])] = {f"ScoreA": x, "ScoreB": y, f"Factor": types[row["Type"]]["MaxFactor"]}
        save_data(row["Datetime"].strftime('%d-%b'), df)


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
            fill_missing(schedule, ss["Types"])
            st.success("Missing bets have been inserted!")
            compute_points(schedule, ss["Types"])
            st.success("Computation of points completed!")
        else:
            st.warning("Password is incorrect.")
