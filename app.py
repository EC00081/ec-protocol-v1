import streamlit as st
import pandas as pd
import time
import math
import hashlib
import requests
from datetime import datetime
from streamlit_js_eval import get_geolocation
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="EC Enterprise", page_icon="🛡️")

# --- CONFIGURATION (TARGET: LUNENBURG, MA) ---
HOSPITAL_LAT = 42.57381188522667
HOSPITAL_LON = -71.74726585573194
GEOFENCE_RADIUS = 300 
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}

# ⚡ HEARTBEAT
count = st_autorefresh(interval=10000, key="pulse")

# --- DATABASE ENGINE ---
def get_db_connection():
    try:
        if "gcp_service_account" not in st.secrets: return None
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        client = gspread.authorize(creds)
        return client
    except: return None

# --- STATE MANAGEMENT ---
if 'user_state' not in st.session_state: 
    st.session_state.user_state = {
        'active': False, 
        'start_time': 0.0, 
        'earnings': 0.0, 
        'locked': False,
        'payout_success': False
    }

# --- BACKEND FUNCTIONS ---
def get_cloud_state(pin):
    client = get_db_connection()
    if not client: return {}
    try:
        sheet = client.open("ec_database").worksheet("workers")
        records = sheet.get_all_records()
        for row in records:
            # FIX: Broken apart for safety
            row_pin = str(row.get('pin'))
            user_pin = str(pin)
            if row_pin == user_pin:
                return row
        return {}
    except: return {}

def update_cloud_status(pin, status, start_time, earnings):
    client = get_db_connection()
    if client
