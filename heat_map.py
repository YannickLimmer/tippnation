import numpy as np
import streamlit as st
import plotly.express as px
from matplotlib import pyplot as plt

from points import collect_complete_match_data, compute_points
from util import ss, get_now


def heat_maps():
    dcols = st.columns(4)
    with dcols[0]:
        date = st.date_input("Choose Date", key="heatmap_date")
    schedule = ss["schedule"][ss["schedule"].Datetime.dt.date == date]
    schedule = schedule[(schedule.Datetime < get_now()).values]
    with dcols[1]:
        match = st.selectbox("Choose Match", options=[a+" vs "+b for a, b in zip(schedule.TeamA, schedule.TeamB)])
        if match is None:
            return
        team_a, team_b = match.split(" vs ")
    match_data = collect_complete_match_data(schedule)
    match_data = match_data[(match_data.TeamA == team_a) & (match_data.TeamB == team_b)]
    with dcols[2]:
        p1 = st.selectbox("Choose Player", options=list(match_data.Name), index=None)
        if p1 is None:
            return
    with dcols[3]:
        p2 = st.selectbox("Choose Opponent", options=[None] + [v for v in list(match_data.Name) if v != p1])

    def get_final_points(result_a, result_b):
        match_data.ResultA = result_a
        match_data.ResultB = result_b
        res = compute_points(match_data).set_index("Name")
        return res.loc[p1, "Final"] - (res.loc[p2, "Final"] if p2 else 0)

    # Create a grid of points for result_a and result_b
    result_a_values = np.arange(0, 6)
    result_b_values = np.arange(0, 6)

    # Compute final points for each combination of result_a and result_b
    final_points = np.zeros((len(result_a_values), len(result_b_values)))
    for i, a in enumerate(result_a_values):
        for j, b in enumerate(result_b_values):
            final_points[i, j] = get_final_points(a, b)

    # Plot the heatmap
    _, mcol, _ = st.columns(3)
    with mcol:
        st.markdown(f"{p1}'s bet: \n {team_a} **{match_data[match_data.Name == p1]['ScoreA'].item()}"
                 f" : {match_data[match_data.Name == p1]['ScoreB'].item()}** {team_b}"
                 f" **x {match_data[match_data.Name == p1]['Factor'].item()}**")
        if p2:
            st.markdown(f"{p2}'s bet: \n {team_a} **{match_data[match_data.Name == p2]['ScoreA'].item()}"
                     f" : {match_data[match_data.Name == p2]['ScoreB'].item()}** {team_b}"
                     f" **x {match_data[match_data.Name == p2]['Factor'].item()}**")
        st.write(f"Points for {p1} depending on outcome:" if p2 is None else
                 f"Points {p1} gets\n more than {p2} depending on outcome:")
        fig = px.imshow(final_points, text_auto=True, x=np.arange(0, 6), y=np.arange(0, 6), aspect="auto",
                        labels=dict(x=f"Goals of {team_b}", y=f"Goals of {team_a}", color="Points"))
        fig.update_xaxes(side="top")
        st.plotly_chart(fig, theme="streamlit")



