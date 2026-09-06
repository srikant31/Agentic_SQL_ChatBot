import streamlit as st


def apply_theme():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        color: #37352F;
    }

    .stApp {
        background-color: #FFFFFF;
    }

    .block-container {
        max-width: 800px;
        padding-top: 3rem;
        padding-bottom: 3rem;
    }

    [data-testid="stSidebar"] {
        background-color: #FBFBFA;
        border-right: 1px solid #E9E9E7;
    }

    h1, h2, h3 {
        color: #37352F;
        font-weight: 600;
        letter-spacing: -0.01em;
    }

    p, .stMarkdown, [data-testid="stCaptionContainer"] {
        color: #6B6B6A;
    }

    .stButton > button {
        background-color: #FFFFFF;
        color: #37352F;
        border: 1px solid #E9E9E7;
        border-radius: 6px;
        font-weight: 500;
        padding: 0.4rem 1rem;
        box-shadow: 0 1px 2px rgba(0,0,0,0.04);
        transition: background-color 0.15s ease;
    }
    .stButton > button:hover {
        background-color: #F7F6F5;
        border-color: #D9D9D6;
        color: #37352F;
    }

    .stButton > button[kind="primary"] {
        background-color: #37352F;
        color: #FFFFFF;
        border: 1px solid #37352F;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #2F2E2A;
    }

    .stTextArea textarea, .stTextInput input, [data-baseweb="select"] {
        background-color: #FFFFFF !important;
        border: 1px solid #E9E9E7 !important;
        border-radius: 6px !important;
        color: #37352F !important;
    }
    .stTextArea textarea:focus, .stTextInput input:focus {
        border-color: #2383E2 !important;
        box-shadow: 0 0 0 1px #2383E2 !important;
    }

    [data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #FFFFFF !important;
        border: 1px solid #E9E9E7 !important;
        border-radius: 8px !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;
        padding: 0.75rem;
    }

    [data-testid="stAlert"] {
        border: 1px solid #E9E9E7;
        border-radius: 6px;
        background-color: #F7F6F5;
        box-shadow: none;
    }

    code, .stCodeBlock {
        background-color: #F7F6F5 !important;
        border: 1px solid #E9E9E7 !important;
        border-radius: 4px;
        color: #37352F !important;
    }

    [data-testid="stMetric"] {
        background-color: #F7F6F5;
        border: 1px solid #E9E9E7;
        border-radius: 6px;
        padding: 0.6rem 0.8rem;
    }
    [data-testid="stMetricLabel"] { color: #6B6B6A; }

    .stProgress > div > div {
        background-color: #2383E2 !important;
        border-radius: 4px;
    }

    [data-testid="stDataFrame"] {
        border: 1px solid #E9E9E7;
        border-radius: 6px;
    }

    hr { border-color: #E9E9E7 !important; }
    </style>
    """, unsafe_allow_html=True)