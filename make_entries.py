import json
import logging

import pandas as pd
import streamlit as st

from points import collect_complete_match_data
from util import get_now, ss, load_data, INDEX_COLUMNS, save_data, country_name_to_flag

streamlit_root_logger = logging.getLogger(st.__name__)
logging.basicConfig(format='%(asctime)s %(levelname)-8s %(message)s', level=logging.INFO, datefmt='%Y-%m-%d %H:%M:%S')


def create_tip_entries(name, matches, data):
    n_cols = len(matches)
    entries = []
    factor_budget = manage_factor_budget(n_cols, name, matches, data)
    fill_default_scores(n_cols, name, matches, data)
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
                            f"Kanonenwilli": None,
                        }
                    )
    return entries


def fill_default_scores(n_cols, name, matches, data):
    factor_budget = 0
    for i in range(n_cols):
        dt, name_a, name_b, t = matches[i]
        for team in ('A', 'B'):
            if f"team_{team}_{i}" not in ss:
                if (name, name_a, name_b) in data.index and not pd.isna(data.loc[(name, name_a, name_b), f"Score{team}"]):
                    ss[f"team_{team}_{i}"] = data.loc[(name, name_a, name_b), :][f"Score{team}"].astype(int)
                else:
                    ss[f"team_{team}_{i}"] = 0
    return factor_budget


def manage_factor_budget(n_cols, name, matches, data):
    factor_budget = 0
    for i in range(n_cols):
        dt, name_a, name_b, t = matches[i]
        factor_budget += ss["Types"][t]["MaxFactor"]
        if f"factor_{i}" not in ss:
            if (name, name_a, name_b) in data.index and not pd.isna(data.loc[(name, name_a, name_b), f"Factor"]):
                ss[f"factor_{i}"] = data.loc[(name, name_a, name_b), :].Factor.astype(int)
            else:
                ss[f"factor_{i}"] = 1  # ss["Types"][t]["MaxFactor"]
    return factor_budget


def create_tip_entry(i, name_a, name_b, dt, n_cols, factor_budget):
    with st.container(border=True):
        st.write(pd.to_datetime(pd.Timestamp(dt)).strftime("%H:%M"))
        cl, cr = st.columns(2)
        with cl:
            team_a_score = st.number_input(name_a + " " + country_name_to_flag(name_a), step=1, key=f"team_A_{i}")
        with cr:
            team_b_score = st.number_input(name_b + " " + country_name_to_flag(name_b), step=1, key=f"team_B_{i}")
        budget = factor_budget - sum([ss[f"factor_{j}"] for j in range(n_cols) if i != j])
        if budget == 1:
            ss[f"factor_{i}"] = 1
            factor = 1
            st.write("Factor is set to 1")
        else:
            factor = st.slider("Factor", 1, budget, key=f"factor_{i}")
    return factor, team_a_score, team_b_score


def delete_defaults():
    for i in range(4):
        for k in (f"factor_{i}", f"team_A_{i}", f"team_B_{i}"):
            if k in ss:
                del ss[k]


def logout():
    ss["login"] = False


YN_EMOJI = {True: ":white_check_mark:", False: ":x:"}


def make_entries():
    # st.title("Score Entries")

    schedule = ss["schedule"]
    user_info = ss["user_info"]

    next_game = schedule[(schedule.Datetime >= get_now()).values].iloc[0]
    next_game_tips = load_data(next_game.Datetime.strftime('%d-%b')).loc[(slice(None), next_game.TeamA, next_game.TeamB), :]

    st.write("Tipped for next game: ", " , ".join([n + " " + YN_EMOJI[
        pd.notna(next_game_tips.loc[(n, next_game.TeamA, next_game.TeamB), "ScoreA"])
    ] for n in user_info.keys()]))
    kws = {n: next_game_tips.loc[(n, next_game.TeamA, next_game.TeamB), "Kanonenwilli"] for n in user_info.keys()}
    st.write("Kanonenwilli for next game: ", " , ".join([
        n + " :rocket: (+" + str(int(kw)) + ")" for n, kw in kws.items() if pd.notna(kw) and kw != 0
    ]))

    if "login" not in ss:
        ss["login"] = False

    cols = st.columns(4)
    with cols[0]:
        name = st.text_input("Username", placeholder="Username", on_change=logout, autocomplete="username", label_visibility='collapsed',)
        # name = st.selectbox("Username", options=list(user_info.keys()), index=None, label_visibility='collapsed', placeholder="Username", on_change=logout)
    with cols[1]:
        pwd = st.text_input("Password", type="password", placeholder="Password", autocomplete="current-password", label_visibility='collapsed')
    with cols[2]:
        if st.button("Login"):
            if name in user_info.keys():
                if pwd == st.secrets[name]["Password"]:
                    ss["login"] = True
                else:
                    st.warning("Password is incorrect. Are you trying to cheat?")
            else:
                st.warning("This user is not registered.")
    with cols[3]:
        if st.button("Logout"):
            ss["login"] = False

    entries = []
    if ss["login"]:
        st.write(f"""Time now: {get_now().strftime("%H:%m")}""")
        cols = st.columns(4)
        with cols[0]:
            date_str = st.date_input("Date of Event", on_change=delete_defaults).strftime('%d-%b')

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
                data.loc[idx, ("ScoreA", "ScoreB", "Factor")] = new_data.loc[idx, :]
            save_data(date_str, data)
            ss["conn"].update(worksheet="Tips", data=collect_complete_match_data(ss["schedule"]))
            st.success("Entries have been saved successfully!")
        else:
            st.warning("Password is incorrect. Are you trying to cheat?")
