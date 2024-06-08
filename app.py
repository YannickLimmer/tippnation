import json
from datetime import datetime

import streamlit as st
import pandas as pd
import os


ss = st.session_state

COLUMNS = ["Name", f"TeamA", f"TeamB", f"ScoreA", "ScoreB", f"Factor"]
INDEX_COLUMNS = ["Name", f"TeamA", f"TeamB"]


# Function to load existing data
def load_data(filepath):
    if os.path.exists(filepath):
        return pd.read_csv(filepath).set_index(INDEX_COLUMNS)
    else:
        return pd.DataFrame(columns=COLUMNS).set_index(INDEX_COLUMNS)


# Function to save data
def save_data(filepath, df):
    df.to_csv(filepath, index=True)


# Function to create columns and input fields
def create_tip_entries(name, matches, factor_budget, data):
    n_cols = len(matches)
    entries = []
    manage_factor_budget(n_cols, name, matches, data)
    for i, col in enumerate(st.columns(4)):
        with col:
            if i < n_cols:
                dt, name_a, name_b = matches[i]
                if pd.Timestamp(dt) > get_now():
                    factor, team_a_score, team_b_score = create_tip_entry(i, name_a, name_b, dt, n_cols, factor_budget)
                    entries.append(
                        {
                            f"Name": name,
                            f"TeamA": name_a,
                            f"TeamB": name_b,
                            f"ScoreA": team_a_score,
                            "ScoreB": team_b_score,
                            f"Factor": factor,
                        }
                    )
    return entries


def manage_factor_budget(n_cols, name, matches, data):
    for i in range(n_cols):
        if f"factor_{i}" not in ss:
            ss[f"factor_{i}"] = 1
        dt, name_a, name_b = matches[i]
        if pd.Timestamp(dt) < get_now():
            if (name, name_a, name_b) in data.index:
                ss[f"factor_{i}"] = data.loc[(name, name_a, name_b), :].Factor.astype(int)
            else:
                ss[f"factor_{i}"] = 0


def get_now():
    # return datetime.now()
    # For testing
    return pd.Timestamp(2024, 6, 19, 19, 0, 0, 0)


def create_tip_entry(i, name_a, name_b, dt, n_cols, factor_budget):
    with st.container(border=True):
        st.write(pd.to_datetime(pd.Timestamp(dt)).strftime("%H:%M"))
        cl, cr = st.columns(2)
        with cl:
            team_a_score = st.number_input(name_a, step=1, key=f"team_a_{i}")
        with cr:
            team_b_score = st.number_input(name_b, step=1, key=f"team_b_{i}")
        used_budget = sum([ss[f"factor_{j}"] for j in range(n_cols) if i != j])
        factor = st.slider("Factor", 1, factor_budget - used_budget, key=f"factor_{i}")
    return factor, team_a_score, team_b_score


# Main function
def make_entries():
    st.title("Team Scores Entry")

    with open("data/Players.json", "r") as fp:
        user_info = json.load(fp)

    schedule = pd.read_csv("data/Schedule.csv")
    schedule["Datetime"] = pd.to_datetime(schedule["Datetime"])
    unique_dates = [s.strftime('%d-%b') for s in schedule.Datetime.dt.date.unique()]

    cols = st.columns(4)
    with cols[0]:
        name = st.selectbox("Select your name", options=list(user_info.keys()))
    with cols[1]:
        pwd = st.text_input("Enter Password", type="password")
    with cols[3]:
        # [datetime.date.today().strftime('%d-%b')]
        date_str = st.selectbox("Date", unique_dates)

    match_indices = schedule.Datetime.dt.date.apply(lambda s: s.strftime('%d-%b')) == date_str
    matches = list(zip(
        schedule["Datetime"].values[match_indices],
        schedule["Team A"].values[match_indices],
        schedule["Team B"].values[match_indices]),
    )

    data_filepath = f"data/tips/{date_str}.csv"
    data = load_data(data_filepath)

    if st.button("Display your current entries"):
        if pwd == user_info[name]["Password"]:
            st.dataframe(data[data.reset_index()["Name"].values == name])
        else:
            st.warning("Password is incorrect. Are you trying to cheat?")

    entries = create_tip_entries(name, matches, 10, data)

    if st.button("Submit"):
        if pwd == user_info[name]["Password"]:
            new_data = pd.DataFrame(entries).set_index(INDEX_COLUMNS)
            for idx in new_data.index:
                data.loc[idx, :] = new_data.loc[idx, :]
            save_data(data_filepath, data)
            st.success("Entries have been saved successfully!")
        else:
            st.warning("Password is incorrect. Are you trying to cheat?")

    # st.dataframe(data)


def main():
    for key, value in ss.items():
        ss[key] = value
    st.set_page_config(layout="wide")
    tabs = st.tabs(["Enter Scores", "View Entries"])
    with tabs[0]:
        make_entries()


if __name__ == "__main__":
    main()
