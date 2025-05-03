import openai
import os
import json
import pdfplumber
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# --- Setup ---
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# --- Constants ---
OUTPUT_DIR = "data"
LEDGER_FILE = os.path.join(OUTPUT_DIR, "ledger.xlsx")
VENDOR_CATEGORY_MAP = {
    "ABCD": "Office Supplies",
    "Google": "IT Services",
    "Staples": "Office Supplies"
}
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Session State ---
if "extracted_data" not in st.session_state:
    st.session_state["extracted_data"] = {}
if "journal_entries" not in st.session_state:
    st.session_state["journal_entries"] = []

# --- App Title ---
st.set_page_config(page_title="LedgerScribe", layout="wide")
st.title("LedgerScribe: Invoice Parser & Journal Generator")

# --- Tabs Layout ---
tabs = st.tabs(["Upload Invoice", "Invoice Details", "Journal Entries", "Ledger History"])

# ========================
# Tab 1: Upload Invoice
# ========================
with tabs[0]:
    uploaded_file = st.file_uploader("Upload Invoice PDF", type=["pdf"])

    if uploaded_file:
        text = ""
        try:
            with pdfplumber.open(uploaded_file) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            st.success("Invoice text extracted.")
            st.text_area("Extracted Invoice Text", text, height=300)

            if st.button("Extract Invoice Fields"):
                with st.spinner("Analyzing with GPT..."):
                    prompt = f"""
You are an AI assistant. Extract the following fields from this invoice text:

- invoice_number
- invoice_date
- vendor_name
- line_items (list of description and amount)
- subtotal
- taxes
- total_amount
- contact_info

Only return a valid JSON object with those fields.

Invoice:
{text}
"""
                    try:
                        response = openai.ChatCompletion.create(
                            model="gpt-4",
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0
                        )
                        result = response.choices[0].message["content"]
                        data = json.loads(result)
                        st.session_state["extracted_data"] = data

                        filename = f"{data.get('vendor_name','unknown')}_{data.get('invoice_number','unknown')}.json"
                        with open(os.path.join(OUTPUT_DIR, filename), "w") as f:
                            json.dump(data, f, indent=2)

                        st.success("Fields extracted and saved.")
                    except Exception as e:
                        st.error(f"Error from GPT: {e}")
        except Exception as e:
            st.error(f"PDF Read Error: {e}")

# ========================
# Tab 2: Invoice Details
# ========================
with tabs[1]:
    data = st.session_state.get("extracted_data", {})
    if data:
        st.subheader("Extracted Invoice Fields")
        st.json(data)
    else:
        st.info("Please upload and extract an invoice first.")

# ============================
# Tab 3: Journal Entries
# ============================
with tabs[2]:
    st.header("Suggested Journal Entries")

    extracted_data = st.session_state.get("extracted_data", {})
    text = st.session_state.get("invoice_text", "")

    if st.button("Suggest Journal Entries"):
        if not extracted_data:
            st.warning("Please extract invoice data first.")
        else:
            amount = extracted_data.get("total_amount", "0").replace("$", "").strip()
            try:
                amount = float(amount)
            except:
                amount = 0.0

            vendor = extracted_data.get("vendor_name", "").strip()
            category = VENDOR_CATEGORY_MAP.get(vendor)

            if not category:
                prompt = f"Suggest an accounting category like 'Office Supplies', 'IT Services', 'Inventory' for this invoice:\n{text}\nReturn just the category name."
                try:
                    response = openai.ChatCompletion.create(
                        model="gpt-4",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0
                    )
                    category = response.choices[0].message["content"].strip()
                    st.info(f"GPT Suggested Category: {category}")
                except Exception as e:
                    category = "Uncategorized"
                    st.warning("GPT failed. Defaulted to 'Uncategorized'.")

            journal_entries = [
                {"debit": category, "credit": "Accounts Payable", "amount": amount}
            ]
            st.session_state["journal_entries"] = journal_entries
            st.success("Suggested journal entries loaded.")

    # Editable Table
    edited_entries = st.data_editor(
        st.session_state.get("journal_entries", [{"debit": "", "credit": "", "amount": 0.0}]),
        num_rows="dynamic",
        use_container_width=True,
        key="editable_journal_entries"
    )

    if st.button("Confirm and Save to Ledger"):
        if not edited_entries:
            st.warning("No journal entries to save.")
        else:
            data = extracted_data
            date = data.get("invoice_date", "Enter invoice date")
            ref = data.get("invoice_number", "unknown")

# Get next sr_no from existing ledger
        if os.path.exists(LEDGER_FILE):
            existing = pd.read_excel(LEDGER_FILE)
            last_sr = existing["sr_no"].max() + 1
        else:
            existing = pd.DataFrame()
            last_sr = 1

            rows = []
            sr = 1
            for entry in edited_entries:
                rows.append({
                    "sr_no": sr,
                    "date": date,
                    "reference": ref,
                    "description": entry["debit"],
                    "debit": entry["amount"],
                    "credit": None
                })
                sr += 1
                rows.append({
                    "sr_no": sr,
                    "date": date,
                    "reference": ref,
                    "description": entry["credit"],
                    "debit": None,
                    "credit": entry["amount"]
                })
                sr += 1

            new_df = pd.DataFrame(rows)

            if os.path.exists(LEDGER_FILE):
                existing = pd.read_excel(LEDGER_FILE)
                combined = pd.concat([existing, new_df], ignore_index=True)
            else:
                combined = new_df

            combined.to_excel(LEDGER_FILE, index=False)
            st.success("Ledger updated.")

# ============================
# Tab 4: Ledger History
# ============================
with tabs[3]:
    st.subheader("Ledger Entries")
    if os.path.exists(LEDGER_FILE):
        df = pd.read_excel(LEDGER_FILE)
        st.dataframe(df)
    else:
        st.info("No ledger records found yet.")
