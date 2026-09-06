import streamlit as st

def apply_theme():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, sans-serif;
        color: #1E1A16;
    }
    .stApp { background-color: #C7A07A; }
    .block-container { max-width: 760px; padding-top: 3rem; padding-bottom: 3rem; }
    h1 { font-weight: 600; font-size: 2.1rem; letter-spacing: -0.01em; color: #1E1A16; }
    [data-testid="stCaptionContainer"] { color: #4A3F35; }
    [data-testid="stSidebar"] { background-color: #C7A07A; border-right: 2px solid #000000; }
    hr, [data-testid="stDivider"] { border-color: #000000 !important; }
    .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {
        background-color: #C7A07A !important;
        border: 1.5px solid #000000 !important;
        border-radius: 4px !important;
        box-shadow: none !important;
        color: #1E1A16 !important;
    }
    .stButton button {
        background-color: #000000;
        color: #F3E6D8;
        border: 1.5px solid #000000;
        border-radius: 4px;
        padding: 0.4rem 1rem;
        font-weight: 500;
        box-shadow: none;
        transition: opacity 0.15s ease;
    }
    .stButton button:hover { opacity: 0.8; color: #F3E6D8; }
    .stButton button:disabled { background-color: transparent; border-color: #4A3F35; color: #4A3F35; }
    [data-testid="stExpander"] { border: 1.5px solid #000000; border-radius: 4px; background-color: #C7A07A; }
    [data-testid="stAlert"] {
        border: 1.5px solid #000000;
        border-radius: 6px;
        background-color: #C7A07A;
        box-shadow: 2px 2px 0px rgba(0,0,0,0.15);
    }
    code, .stCodeBlock {
        background-color: #B78F68 !important;
        border: 1px solid #000000 !important;
        border-radius: 4px;
        color: #1E1A16 !important;
    }

    /* Card-style container — used to visually group the proposed-query
       section so it reads as one distinct step, not a run of loose widgets. */
    [data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #D9B792 !important;
        border: 1.5px solid #000000 !important;
        border-radius: 8px !important;
        box-shadow: 3px 3px 0px rgba(0,0,0,0.2) !important;
        padding: 0.5rem;
    }

    /* Metric widget (used for the session question counter) */
    [data-testid="stMetric"] {
        background-color: #D9B792;
        border: 1.5px solid #000000;
        border-radius: 6px;
        padding: 0.6rem 0.8rem;
        box-shadow: 2px 2px 0px rgba(0,0,0,0.15);
    }
    [data-testid="stMetricLabel"] { color: #4A3F35; }

    /* Progress bar (used for the confidence indicator) */
    .stProgress > div > div {
        background-color: #000000 !important;
        border-radius: 4px;
    }
    </style>
    """, unsafe_allow_html=True)