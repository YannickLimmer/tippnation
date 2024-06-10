import pandas as pd
import streamlit as st

from util import get_now, ss, load_data, INDEX_COLUMNS, save_data, country_name_to_flag


def create_tip_entries(name, matches, data):
    n_cols = len(matches)
    entries = []
    factor_budget = manage_factor_budget(n_cols, name, matches, data)
    for i, col in enumerate(st.columns(4)):
        with col:
            if i < n_cols:
                dt, name_a, name_b, _ = matches[i]
                if pd.Timestamp(dt) > get_now():
                    factor, score_a, score_b = create_tip_entry(i, name_a, name_b, dt, n_cols, factor_budget)
                    entries.append(
                        {
                            f"Name": name,
                            f"TeamA": name_a,
                            f"TeamB": name_b,
                            f"ScoreA": score_a,
                            "ScoreB": score_b,
                            f"Factor": factor,
                        }
                    )
    return entries


def manage_factor_budget(n_cols, name, matches, data):
    factor_budget = 0
    for i in range(n_cols):
        if f"factor_{i}" not in ss:
            ss[f"factor_{i}"] = 1
        dt, name_a, name_b, t = matches[i]
        factor_budget += ss["Types"][t]["MaxFactor"]
        if pd.Timestamp(dt) < get_now():
            if (name, name_a, name_b) in data.index:
                ss[f"factor_{i}"] = data.loc[(name, name_a, name_b), :].Factor.astype(int)
            else:
                ss[f"factor_{i}"] = ss["Types"][t]["MaxFactor"]
    return factor_budget


def create_tip_entry(i, name_a, name_b, dt, n_cols, factor_budget):
    with st.container(border=True):
        st.write(pd.to_datetime(pd.Timestamp(dt)).strftime("%H:%M"))
        cl, cr = st.columns(2)
        with cl:
            team_a_score = st.number_input(name_a + " " + country_name_to_flag(name_a), step=1, key=f"team_a_{i}")
        with cr:
            team_b_score = st.number_input(name_b + " " + country_name_to_flag(name_b), step=1, key=f"team_b_{i}")
        budget = factor_budget - sum([ss[f"factor_{j}"] for j in range(n_cols) if i != j])
        if budget == 1:
            ss[f"factor_{i}"] = 1
            factor = 1
            st.write("Factor is set to 1")
        else:
            factor = st.slider("Factor", 1, budget, key=f"factor_{i}")
    return factor, team_a_score, team_b_score


def make_entries():
    # st.title("Score Entries")

    schedule = ss["schedule"]
    user_info = ss["user_info"]

    cols = st.columns(4)
    with cols[0]:
        name = st.selectbox("Select your name", options=list(user_info.keys()), index=None, label_visibility='collapsed', placeholder="Select your name")
    with cols[1]:
        pwd = st.text_input("Enter Password", type="password", label_visibility='collapsed', placeholder="Enter Password")
    with cols[2]:
        if "login" not in ss:
            ss["login"] = False
        if st.button("Login"):
            if pwd == st.secrets[name]["Password"]:
                ss["login"] = True
            else:
                st.warning("Password is incorrect. Are you trying to cheat?")
    with cols[3]:
        if st.button("Logout"):
            ss["login"] = False

    entries = []
    if ss["login"]:
        cols = st.columns(4)
        with cols[0]:
            date_str = st.date_input("Date of Event").strftime('%d-%b')

        match_indices = schedule.Datetime.dt.date.apply(lambda s: s.strftime('%d-%b')) == date_str
        matches = list(zip(
            schedule["Datetime"].values[match_indices],
            schedule["TeamA"].values[match_indices],
            schedule["TeamB"].values[match_indices],
            schedule["Type"].values[match_indices],
        ))

        data = load_data(date_str)
        # st.dataframe(data[data.reset_index()["Name"].values == name])
        entries = create_tip_entries(name, matches, data)

    button = False
    if entries:
        st.write("You can only submit all matches at once, but you can change your entries until each game starts!")
        button = st.button("Submit")
    else:
        if ss["login"]:
            st.info("There are no games on this day. Choose a date with events!")

    if button:
        if pwd == st.secrets[name]["Password"]:
            new_data = pd.DataFrame(entries).set_index(INDEX_COLUMNS)
            for idx in new_data.index:
                data.loc[idx, :] = new_data.loc[idx, :]
            save_data(date_str, data)
            st.success("Entries have been saved successfully!")
        else:
            st.warning("Password is incorrect. Are you trying to cheat?")
