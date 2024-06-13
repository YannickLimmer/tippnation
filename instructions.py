import streamlit as st
from util import ROOT


def read_markdown(file_path):
    with open(file_path, 'r') as file:
        return file.read()


def display_instructions():
    language = st.selectbox("Choose language", ["Deutsch", "English"])
    if language == "Deutsch":
        st.markdown(read_markdown(ROOT + "/Instructions_DE.md"))
    else:
        st.markdown(read_markdown(ROOT + "/Instructions_EN.md"))
