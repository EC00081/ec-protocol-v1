import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import time
import random
from datetime import datetime
from fpdf import FPDF
import base64

# --- CONFIG ---
st.set_page_config(page_title="Gilford Son & Co.", page_icon="🛡️")

if 'pool' not in st.session_state: st.session_state.pool = 50000.0
if 'revenue' not in st.session_state: st.session_state.revenue = 0.0
if 'ledger' not in st.session_state: st.session_state.ledger = []
if 'history' not in st.session_state: st.session_state.history = [50000.0]

# --- PDF FUNCTION ---
def create_pdf(amount):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="GILFORD SON & CO. | OFFICIAL RECEIPT", ln=1, align='C')
    pdf.line(10, 20, 200, 20)
    pdf.ln(10)
    pdf.cell(200, 10, txt=f"Date: {datetime.now().strftime('%Y-%m-%d')}", ln=1)
    pdf.cell(200, 10, txt=f"Amount Settled: ${amount:.2f}", ln=1)
    pdf.cell(200, 10, txt="Status: CONFIRMED", ln=1)
    return pdf.output(dest='S').encode('latin-1')

# --- UI ---
st.title("🛡️ Gilford Son & Co.")
st.caption("EC PROTOCOL | LIVE DEPLOYMENT")

mode = st.radio("Mode", ["Live", "Investor Demo"])

col1, col2 = st.columns(2)
col1.metric("Network Liquidity", f"${st.session_state.pool:,.2f}")
col2.metric("Protocol Revenue", f"${st.session_state.revenue:,.2f}")

st.line_chart(st.session_state.history)

if mode == "Live":
    if st.button("Clock In"):
        st.session_state.pool -= 0.50
        st.session_state.ledger.append("IN: Manual User")
        st.session_state.history.append(st.session_state.pool)
        st.success("Clocked In")
        
    if st.button("Settle Shift"):
        amt = 100.0
        st.session_state.pool -= amt
        st.session_state.revenue += (amt * 0.02)
        st.session_state.ledger.append("OUT: Manual User")
        st.session_state.history.append(st.session_state.pool)
        st.success("Shift Settled")

else:
    if st.button("▶️ RUN DEMO"):
        st.session_state.pool = 50000.0
        st.session_state.history = [50000.0]
        
        with st.spinner("Running Simulation..."):
            time.sleep(1)
            st.session_state.pool -= 0.50
            st.toast("✅ Clock In Verified")
            time.sleep(1)
            for i in range(5):
                st.session_state.pool -= 50
                st.session_state.history.append(st.session_state.pool)
                time.sleep(0.1)
            
            st.session_state.revenue += 20.0
            st.session_state.ledger.append("DEMO COMPLETE")
            st.success("💰 Payment Settled: $1,020.00")
            
            pdf = create_pdf(1020.00)
            st.download_button("📄 Download Receipt", data=pdf, file_name="receipt.pdf")

st.write("### Recent Activity")
for l in reversed(st.session_state.ledger[-5:]):
    st.text(l)
