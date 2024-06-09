import pandas as pd
import streamlit as st

from util import get_now, ss, load_data, INDEX_COLUMNS, save_data, country_name_to_flag


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


def create_tip_entry(i, name_a, name_b, dt, n_cols, factor_budget):
    with st.container(border=True):
        st.write(pd.to_datetime(pd.Timestamp(dt)).strftime("%H:%M"))
        cl, cr = st.columns(2)
        with cl:
            team_a_score = st.number_input(name_a + " " + country_name_to_flag(name_a), step=1, key=f"team_a_{i}")
        with cr:
            team_b_score = st.number_input(name_b + " " + country_name_to_flag(name_b), step=1, key=f"team_b_{i}")
        used_budget = sum([ss[f"factor_{j}"] for j in range(n_cols) if i != j])
        factor = st.slider("Factor", 1, factor_budget - used_budget, key=f"factor_{i}")
    return factor, team_a_score, team_b_score


def make_entries():
    # st.title("Score Entries")

    schedule = ss["schedule"]
    user_info = ss["user_info"]

    cols = st.columns(4)
    with cols[0]:
        name = st.selectbox("Select your name", options=list(user_info.keys()))
    with cols[1]:
        pwd = st.text_input("Enter Password", type="password")
    with cols[3]:
        date_str = st.date_input("Date").strftime('%d-%b')

    match_indices = schedule.Datetime.dt.date.apply(lambda s: s.strftime('%d-%b')) == date_str
    matches = list(zip(
        schedule["Datetime"].values[match_indices],
        schedule["TeamA"].values[match_indices],
        schedule["TeamB"].values[match_indices]),
    )

    data = load_data(date_str)

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
            save_data(date_str, data)
            st.success("Entries have been saved successfully!")
        else:
            st.warning("Password is incorrect. Are you trying to cheat?")
