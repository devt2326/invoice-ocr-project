import os
import json
import pandas as pd
import streamlit as st
import pdfplumber
import openai
from dotenv import load_dotenv
from datetime import datetime

# Load OpenAI key
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

st.set_page_config(page_title="Invoice OCR Parser", layout="centered")
st.title("Invoice OCR Parser")

uploaded_file = st.file_uploader("Upload Invoice PDF", type=["pdf"])
if "invoice_data" not in st.session_state:
    st.session_state.invoice_data = None
if "journal_entries" not in st.session_state:
    st.session_state.journal_entries = None

# Extract invoice text
text = ""
if uploaded_file:
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        if text.strip():
            st.subheader("Extracted Invoice Text")
            st.text(text)
        else:
            st.warning("No extractable text found in the PDF.")
    except Exception as e:
        st.error(f"Error reading PDF: {e}")

# Extract invoice fields
if text.strip():
    if st.button("Extract Detailed Fields"):
        with st.spinner("Analyzing invoice with GPT..."):
            prompt = f"""
You are an invoice parser. Extract the following fields from this invoice text:

- invoice_number
- invoice_date
- vendor_name
- line_items (each with description and amount)
- subtotal
- taxes
- total_amount
- contact_info

Return a valid JSON object with these fields only.

Invoice text:
{text}
"""
            try:
                response = openai.ChatCompletion.create(
                    model="gpt-4",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0
                )
                result = response.choices[0].message["content"].strip()
                data = json.loads(result)
                st.session_state.invoice_data = data
                st.subheader("Extracted Detailed Invoice Fields")
                st.json(data)
            except Exception as e:
                st.error(f"Error calling GPT: {e}")

# Suggest journal entries at invoice level
if st.session_state.invoice_data:
    if st.button("Suggest Journal Entries"):
        with st.spinner("Generating journal entries..."):
            invoice_data = st.session_state.invoice_data
            prompt = f"""
You are a finance assistant. Based on the following invoice data, generate a single journal entry at the invoice level.

Only return one consolidated entry. Choose the debit account based on the context.

Return JSON in this format:
[
  {{
    "debit": "Expense Category",
    "credit": "Accounts Payable",
    "amount": 150.00
  }}
]

Invoice:
{json.dumps(invoice_data, indent=2)}
"""
            try:
                response = openai.ChatCompletion.create(
                    model="gpt-4",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0
                )
                raw_output = response.choices[0].message["content"]
                st.subheader("Raw GPT Output")
                st.code(raw_output, language="json")

                try:
                    journal_data = json.loads(raw_output)
                    st.session_state.journal_entries = journal_data
                    st.subheader("Suggested Journal Entries")
                    st.json(journal_data)
                except json.JSONDecodeError as e:
                    st.error(f"Invalid JSON returned from GPT: {e}")
            except Exception as e:
                st.error(f"Error during GPT call: {e}")

# Save journal entries to ledger
if st.session_state.journal_entries and st.session_state.invoice_data:
    if st.button("Confirm and Save to Ledger"):
        invoice = st.session_state.invoice_data
        entries = st.session_state.journal_entries
        invoice_date = invoice.get("invoice_date", str(datetime.today().date()))
        reference = invoice.get("invoice_number", "UNKNOWN")

        ledger_rows = []
        for entry in entries:
            ledger_rows.append({
                "sr_no": None,
                "date": invoice_date,
                "reference": reference,
                "description": entry["debit"],
                "debit": entry["amount"],
                "credit": ""
            })
            ledger_rows.append({
                "sr_no": None,
                "date": invoice_date,
                "reference": reference,
                "description": entry["credit"],
                "debit": "",
                "credit": entry["amount"]
            })

        os.makedirs("outputs", exist_ok=True)
        ledger_path = "outputs/ledger.xlsx"

        if os.path.exists(ledger_path):
            df = pd.read_excel(ledger_path)
        else:
            df = pd.DataFrame(columns=["sr_no", "date", "reference", "description", "debit", "credit"])

        df = pd.concat([df, pd.DataFrame(ledger_rows)], ignore_index=True)
        df["sr_no"] = range(1, len(df) + 1)
        df.to_excel(ledger_path, index=False)

        st.success("Journal entries saved to ledger successfully.")
        st.write(df.tail(10))
