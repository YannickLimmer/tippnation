import os
from datetime import datetime

import pandas as pd
import streamlit as st
from pytz import timezone

ss = st.session_state
COLUMNS = ["Name", f"TeamA", f"TeamB", f"ScoreA", "ScoreB", f"Factor", f"Kanonenwilli"]
DTYPES = {"Name": str, f"TeamA": str, f"TeamB": str, f"ScoreA": int, "ScoreB": int, f"Factor": int, f"Kanonenwilli": 'Int64'}
INDEX_COLUMNS = ["Name", f"TeamA", f"TeamB"]
DEV_FLAG = True
ROOT = os.getcwd()
SNS_COLORS = [
    '#a1c9f4', '#ffb482', '#8de5a1', '#ff9f9b', '#d0bbff', '#debb9b', '#fab0e4', '#cfcfcf', '#fffea3', '#b9f2f0'
]


def load_data(date_str):
    filepath = ROOT + f"/data/tips/{date_str}.csv"
    if os.path.exists(filepath):
        df = pd.read_csv(filepath, dtype=DTYPES).set_index(INDEX_COLUMNS)
        if "Kanonenwilli" not in df.columns:
            df["Kanonenwilli"] = None
        return df
    else:
        return pd.DataFrame(columns=COLUMNS).set_index(INDEX_COLUMNS)


def save_data(date_str, df):
    filepath = ROOT + f"/data/tips/{date_str}.csv"
    df.to_csv(filepath, index=True)


def get_now():
    if DEV_FLAG:
        return datetime.combine(ss["dev_date"], ss["dev_time"])

    return datetime.now(timezone("Europe/Berlin")).replace(tzinfo=None)


FLAG_DICT = {
     'Albania': '🇦🇱',
     'Austria': '🇦🇹',
     'Belgium': '🇧🇪',
     'Croatia': '🇭🇷',
     'Czech Republic': '🇨🇿',
     'Denmark': '🇩🇰',
     'England': '🏴\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f',
     'France': '🇫🇷',
     'Georgia': '🇬🇪',
     'Germany': '🇩🇪',
     'Hungary': '🇭🇺',
     'Italy': '🇮🇹',
     'Netherlands': '🇳🇱',
     'Poland': '🇵🇱',
     'Portugal': '🇵🇹',
     'Romania': '🇷🇴',
     'Scotland': '🏴\U000e0067\U000e0062\U000e0073\U000e0063\U000e0074\U000e007f',
     'Serbia': '🇷🇸',
     'Slovakia': '🇸🇰',
     'Slovenia': '🇸🇮',
     'Spain': '🇪🇸',
     'Switzerland': '🇨🇭',
     'Turkey': '🇹🇷',
     'Ukraine': '🇺🇦',
     'Wales': '🏴\U000e0067\U000e0062\U000e0077\U000e006c\U000e0073\U000e007f'
}


def country_name_to_flag(country_name):
    return FLAG_DICT.get(country_name, "")
    # try:
    #     # Get the country alpha_2 code using pycountry
    #     country = pycountry.countries.get(name=country_name)
    #     if not country:
    #         return ""
    #
    #     # Convert the alpha_2 code to the corresponding emoji
    #     code = country.alpha_2
    #     flag = chr(ord(code[0]) + 127397) + chr(ord(code[1]) + 127397)
    #     return flag
    # except Exception as e:
    #     return ""

