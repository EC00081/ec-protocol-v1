import streamlit as st
import pandas as pd
import time
import math
import requests
import pytz
import base64
import uuid
import numpy as np
from datetime import datetime
from streamlit_js_eval import get_geolocation
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from streamlit_autorefresh import st_autorefresh

# --- 0. LIGHTWEIGHT LIBRARY LOADER ---
try:
    import face_recognition
    from shapely.geometry import Point, Polygon
    BIO_ENGINE_AVAILABLE = True
except ImportError:
    BIO_ENGINE_AVAILABLE = False
    # Fallback classes for demo to prevent crashing
    class Point:
        def __init__(self, x, y): self.x, self.y = x, y
    class Polygon:
        def __init__(self, points): self.points = points
        def contains(self, point): return True 

# --- 1. CONFIGURATION ---
st.set_page_config(
    page_title="EC Enterprise", 
    page_icon="🛡️", 
    layout="centered", 
    initial_sidebar_state="expanded"
)

st.markdown("""
    <head>
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="theme-color" content="#0E1117">
    </head>
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stApp { background: radial-gradient(circle at 50% -20%, #1c2331, #0E1117); color: #FFFFFF; font-family: 'Inter', sans-serif; }
    div[data-testid="stMap"] { border-radius: 16px; overflow: hidden; border: 1px solid rgba(255,255,255,0.2); }
    .status-pill { display: flex; align-items: center; justify-content: center; padding: 12px; border-radius: 50px; font-weight: 600; margin-bottom: 20px; backdrop-filter: blur(10px); }
    .safe-mode { background: rgba(28, 79, 46, 0.4); border: 1px solid #2e7d32; color: #4caf50; }
    .danger-mode { background: rgba(79, 28, 28, 0.4); border: 1px solid #c62828; color: #ff5252; }
    div[data-testid="metric-container"] { background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 16px; }
    .stButton>button { width: 100%; height: 60px; border-radius: 12px; font-weight: 700; border: none; }
    .hero-header { text-align: center; padding: 30px 20px; background: linear-gradient(180deg, rgba(14,17,23,0) 0%, rgba(14,17,23,1) 100%), url("https://images.unsplash.com/photo-1550751827-4bd374c3f58b?q=80&w=2670&auto=format&fit=crop"); background-size: cover; border-radius: 0 0 24px 24px; margin-top: -60px; margin-bottom: 30px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. CONSTANTS ---
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}
LOCAL_TZ = pytz.timezone('US/Eastern')
BROCKTON_POLYGON_COORDS = [(42.0880, -70.9920), (42.0880, -70.9910), (42.0870, -70.9910), (42.0870, -70.9920)]
HOSPITAL_FENCE = Polygon(BROCKTON_POLYGON_COORDS)
GEOFENCE_RADIUS = 45 # Fallback radius

def get_local_now(): return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S EST")

USERS = {
    "1001": {"name": "Liam O'Neil", "role": "RRT", "rate": 85.00, "lat": 42.0875, "lon": -70.9915, "location": "Brockton"},
    "1002": {"name": "Charles Morgan", "role": "RRT", "rate": 85.00, "lat": 42.0875, "lon": -70.9915, "location": "Brockton"},
    "9999": {"name": "CFO VIEW", "role": "Exec", "rate": 0.00}
}

# --- 3. LOGIC ENGINE ---
def verify_polygon_access(user_lat, user_lon):
    if not BIO_ENGINE_AVAILABLE:
        # Fallback Radius Check
        target_lat = 42.0875
        target_lon = -70.9915
        R = 6371000
        lat1, lon1 = math.radians(user_lat), math.radians(user_lon)
        lat2, lon2 = math.radians(target_lat), math.radians(target_lon)
        a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2) * math.sin((lon2-lon1)/2)**2
        dist = R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))
        return dist < GEOFENCE_RADIUS
    point = Point(user_lat, user_lon)
    return HOSPITAL_FENCE.contains(point)

def process_biometric_hash(image_upload):
    if not BIO_ENGINE_AVAILABLE:
        time.sleep(1.0) # Simulate processing time
        return True, "SIMULATED_HASH"
    try:
        img = face_recognition.load_image_file(image_upload)
        face_locations = face_recognition.face_locations(img)
        if len(face_locations) != 1: return False, f"Liveness Check Failed: {len(face_locations)} faces detected."
        return True, face_recognition.face_encodings(img, face_locations)[0]
    except Exception as e: return False, str(e)

# --- 4. BACKEND ---
def get_db_connection():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        return gspread.authorize(creds)
    except: return None

def get_current_ip():
    try: return requests.get('https://api.ipify.org', timeout=1).text
    except: return "Unknown"

def get_cloud_state(pin):
    client = get_db_connection()
    if not client: return {}
    try:
        sheet = client.open("ec_database").worksheet("workers")
        records = sheet.get_all_records()
        target = str(pin).strip()
        for row in records:
            for k, v in row.items():
                if str(k).lower().strip() == 'pin' and str(v).strip() == target:
                    return row
        return {}
    except: return {}

def update_cloud_status(pin, status, start, earn):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("workers")
            try:
                cell = sheet.find(str(pin))
                sheet.update_cell(cell.row, 2, status)
                sheet.update_cell(cell.row, 3, str(start))
                sheet.update_cell(cell.row, 4, str(earn))
                sheet.update_cell(cell.row, 5, get_local_now())
            except:
                sheet.append_row([str(pin), status, str(start), str(earn), get_local_now()])
        except: pass

def log_transaction(pin, amount):
    tx_id = f"TX-{int(time.time())}"
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("transactions")
            sheet.append_row([tx_id, str(pin), f"${amount:.2f}", get_local_now(), "INSTANT"])
        except: pass
    return tx_id

def log_history(pin, action, amount, note):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("history")
            sheet.append_row([str(pin), action, get_local_now(), f"${amount:.2f}", note])
        except: pass

def log_schedule(pin, d, s, e):
    client = get_db_connection()
    if client:
        try:
            dt_s = datetime.combine(d, s).strftime("%Y-%m-%d %H:%M:%S EST")
            dt_e = datetime.combine(d, e).strftime("%Y-%m-%d %H:%M:%S EST")
            sheet = client.open("ec_database").worksheet("schedule")
            sheet.append_row([str(pin), str(d), dt_s, dt_e, "Scheduled"])
            return True
        except: return False
    return False

def post_shift_to_market(pin, role, d, s, e, rate):
    client = get_db_connection()
    if client:
        try:
            shift_id = str(uuid.uuid4())[:8]
            s_str = s.strftime("%H:%M EST")
            e_str = e.strftime("%H:%M EST")
            sheet = client.open("ec_database").worksheet("marketplace")
            sheet.append_row([shift_id, str(pin), role, str(d), s_str, e_str, str(rate), "OPEN"])
            return True
        except: return False
    return False

def claim_shift(shift_id, claimer_pin):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("marketplace")
            cell = sheet.find(shift_id)
            sheet.update_cell(cell.row, 8, f"CLAIMED BY {claimer_pin}")
            return True
        except: return False
    return False

def create_receipt_html(user_name,
