import base64

import streamlit as st
from util import ROOT


def read_markdown(file_path):
    with open(file_path, 'r') as file:
        return file.read()


# Function to convert an image file to a base64 string
def image_to_base64(image_path):
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode("utf-8")


def display_instructions():
    language = st.selectbox("Choose language", ["Deutsch", "English"])
    base64_image = image_to_base64(ROOT + "/data/figs/Bullet_Bill.png")
    image_tag = f"![Bullet Bill](data:image/png;base64,{base64_image})"
    image_tag = f'<img src="data:image/png;base64,{base64_image}" alt="Bullet Bill" width="300"/>'
    if language == "Deutsch":
        with st.expander("Tippen Anleitung"):
            st.markdown(
                read_markdown(ROOT + "/MANUAL_DE.md"),
                unsafe_allow_html=True,
            )
        with st.expander("Punkte Berechnung"):
            st.markdown(
                read_markdown(ROOT + "/Instructions_DE.md").replace("![Sample Image](data/figs/Bullet_Bill.png)", image_tag),
                unsafe_allow_html=True,
            )
    else:
        with st.expander("Instructions for Placing Bets"):
            st.markdown(
                read_markdown(ROOT + "/MANUAL_EN.md"),
                unsafe_allow_html=True,
            )
        with st.expander("Points Computation"):
            st.markdown(
                read_markdown(ROOT + "/Instructions_EN.md").replace("![Sample Image](data/figs/Bullet_Bill.png)", image_tag),
                unsafe_allow_html=True,
            )
