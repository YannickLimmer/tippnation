import io
import os
import zipfile

import numpy as np
import pandas as pd
import streamlit as st

from points import compute_and_save_points
from util import ss, ROOT, get_now, load_data, save_data, logging, DTYPES, INDEX_COLUMNS

# Parameters
LAMBDA_A = 1.2
LAMBDA_B = 1.2
LAMBDA_AB = 0.1


def simulate_outcome(t):
    n = np.random.poisson(LAMBDA_AB)
    x = np.random.poisson(LAMBDA_A) + n
    y = np.random.poisson(LAMBDA_B) + n
    if t != "Group" and x == y:
        return simulate_outcome(t)
    return x, y


def fill_missing(schedule):
    types = ss["Types"]
    for i, row in schedule[(schedule.Datetime < get_now()).values].iterrows():
        df = load_data(row["Datetime"].strftime('%d-%b'))
        for name in ss["user_info"].keys():
            if (name, row["TeamA"], row["TeamB"]) not in df.index or pd.isna(df.loc[(name, row["TeamA"], row["TeamB"]), "ScoreA"]):
                st.info(f"Fill in data for {name, row['TeamA'], row['TeamB']} at date {row['Datetime'].strftime('%d-%b')}")
                x, y = simulate_outcome(row["Type"])
                df.loc[(name, row["TeamA"], row["TeamB"]), ("ScoreA", "ScoreB", "Factor")] = x, y, types[row["Type"]]["MaxFactor"]
        save_data(row["Datetime"].strftime('%d-%b'), df)
    for i, row in schedule[(schedule.Datetime > get_now()).values].iterrows():
        df = load_data(row["Datetime"].strftime('%d-%b'))
        for name in ss["user_info"].keys():
            if (name, row["TeamA"], row["TeamB"]) not in df.index:
                df.loc[(name, row["TeamA"], row["TeamB"])] = None
        save_data(row["Datetime"].strftime('%d-%b'), df)



def zip_csv_files(folder_path):
    # Create a byte stream to hold the zip file in memory
    zip_buffer = io.BytesIO()

    # Create a zip file
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Iterate over all files in the folder
        for foldername, subfolders, filenames in os.walk(folder_path):
            for filename in filenames:
                # Only add CSV files to the zip
                if filename.endswith('.csv'):
                    filepath = os.path.join(foldername, filename)
                    zip_file.write(filepath, os.path.relpath(filepath, folder_path))

        zip_file.write(ROOT + "/data/schedule.csv")

    # Seek to the beginning of the byte stream
    zip_buffer.seek(0)
    return zip_buffer


def admin():
    pwd = st.text_input("Enter Admin Password", type="password")

    tips = st.file_uploader("Upload tips", type="csv", accept_multiple_files=True)
    tip_dfs = {}
    for tip in tips:
        tip_dfs[tip.name[:-4]] = pd.read_csv(tip, dtype=DTYPES).set_index(INDEX_COLUMNS)
        st.write(tip_dfs[tip.name[:-4]])

    if st.button("Save files"):
        if pwd == st.secrets["Admin"]["Password"]:
            for date_str, tip_df in tip_dfs.items():
                save_data(date_str, tip_df)
            st.success("Files uploaded.")
        else:
            st.warning("Password incorrect.")

    uploaded_file = st.file_uploader("Upload a schedule", type="csv")

    # Check if a file has been uploaded
    if uploaded_file is not None:
        # Read the CSV file into a Pandas DataFrame
        ss["schedule"] = pd.read_csv(uploaded_file)
        ss["schedule"]["Datetime"] = pd.to_datetime(ss["schedule"]["Datetime"], dayfirst=True)

    schedule = st.data_editor(ss["schedule"], hide_index=True, num_rows="dynamic", column_config={
                "Datetime": st.column_config.DateColumn("Date", format="DD-MMM, HH:mm")
    })

    if st.button("Save and Compute Points"):
        if pwd == st.secrets["Admin"]["Password"]:
            schedule.to_csv(ROOT + "/data/Schedule.csv")
            st.success("Changes have been saved successfully!")
            fill_missing(schedule)
            st.success("Missing bets have been inserted!")
            compute_and_save_points(schedule)
            st.success("Computation of points completed!")
        else:
            st.warning("Password is incorrect.")

    if st.button("Request all tips"):
        if pwd == st.secrets["Admin"]["Password"]:
            try:
                # Create the zip file
                zip_buffer = zip_csv_files(ROOT + "/data/tips/")

                # Provide the download button for the zip file
                st.download_button(
                    label="Download ZIP",
                    data=zip_buffer,
                    file_name="tips.zip",
                    mime="application/zip"
                )

            except Exception as e:
                st.error(f"An error occurred: {e}")
        else:
            st.warning("Password is incorrect.")
