import streamlit as st

# Palette (darkest to lightest):
# #06141B  main background
# #11212D  sidebar / secondary background / card fill
# #253745  borders, dividers, subtle fills
# #4A5C6A  hover states, stronger borders
# #9BA8AB  muted/secondary text, accents
# #CCD0CF  primary text, high-emphasis elements


def apply_theme():
    st.markdown("""
    <style>
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        color: #CCD0CF;
    }

    .stApp {
        background-color: #06141B;
    }

    .block-container {
        max-width: 800px;
        padding-top: 3rem;
        padding-bottom: 3rem;
    }

    [data-testid="stSidebar"] {
        background-color: #11212D;
        border-right: 1px solid #253745;
    }

    h1, h2, h3 {
        color: #CCD0CF;
        font-weight: 600;
        letter-spacing: -0.01em;
    }

    p, .stMarkdown {
        color: #CCD0CF;
    }
    [data-testid="stCaptionContainer"] {
        color: #B8C4C6 !important;
        opacity: 1 !important;
    }

    .stButton > button {
        background-color: #11212D;
        color: #CCD0CF;
        border: 1px solid #4A5C6A;
        border-radius: 6px;
        font-weight: 500;
        padding: 0.4rem 1rem;
        transition: background-color 0.15s ease;
    }
    .stButton > button:hover {
        background-color: #253745;
        border-color: #9BA8AB;
        color: #CCD0CF;
    }

    .stButton > button[kind="primary"] {
        background-color: #CCD0CF;
        color: #06141B;
        border: 1px solid #CCD0CF;
        font-weight: 600;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #9BA8AB;
        border-color: #9BA8AB;
    }

    .stButton > button:disabled,
    .stButton > button:disabled:hover {
        background-color: #11212D !important;
        color: #4A5C6A !important;
        border: 1px solid #253745 !important;
        opacity: 1 !important;
        cursor: not-allowed;
    }

    .stTextArea textarea, .stTextInput input, [data-baseweb="select"] {
        background-color: #11212D !important;
        border: 1px solid #253745 !important;
        border-radius: 6px !important;
        color: #CCD0CF !important;
    }
    .stTextArea textarea:focus, .stTextInput input:focus {
        border-color: #9BA8AB !important;
        box-shadow: 0 0 0 1px #9BA8AB !important;
    }

    [data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #11212D !important;
        border: 1px solid #253745 !important;
        border-radius: 8px !important;
        padding: 0.75rem;
    }

    [data-testid="stAlert"] {
        border: 1px solid #253745;
        border-radius: 6px;
        background-color: #11212D;
        color: #CCD0CF;
    }

    code, .stCodeBlock {
        background-color: #11212D !important;
        border: 1px solid #253745 !important;
        border-radius: 4px;
        color: #CCD0CF !important;
    }

    [data-testid="stMetric"] {
        background-color: #11212D;
        border: 1px solid #253745;
        border-radius: 6px;
        padding: 0.6rem 0.8rem;
    }
    [data-testid="stMetricLabel"] { color: #B8C4C6; }
    [data-testid="stMetricValue"] { color: #CCD0CF; }

    .stProgress > div > div {
        background-color: #CCD0CF !important;
        border-radius: 4px;
    }

    [data-testid="stDataFrame"] {
        border: 1px solid #253745;
        border-radius: 6px;
    }

    hr { border-color: #253745 !important; }
    </style>
    """, unsafe_allow_html=True)