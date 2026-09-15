# Hybrid Real-Time Credit Card Fraud Detection System

A hybrid credit card fraud detection system that combines ensemble machine learning, Quantum-Inspired Optimization (QIO) and Explainable AI (SHAP) with a live monitoring dashboard and a sandbox payment app for testing (SimplePay).

## Project Structure

- **Python API (FastAPI)** - trains and serves the ensemble fraud detection models, handles feature selection and generates SHAP explanations
- **Streamlit App** - a lightweight interface for testing single transactions and viewing model performance
- **PHP/Tailwind Admin Dashboard (smartDetector)** - the live monitoring dashboard used by fraud investigators
- **SimplePay** - a sandbox payment web app used to simulate real transactions and trigger fraud checks

## Prerequisites

- [XAMPP](https://www.apachefriends.org/) (for Apache and MySQL)
- Python 3.9 or higher
- VS Code (or any code editor/terminal)
- Required Python packages installed (see `requirements.txt` if available, otherwise install `fastapi`, `uvicorn`, `scikit-learn`, `xgboost`, `shap` and `streamlit`)

## How to Run

1. **Start XAMPP**
   Open XAMPP and start the **Apache** and **MySQL** modules. This powers the PHP backend and database used by the admin dashboard and SimplePay.

2. **Start the Python API**
   Open VS Code, open a terminal and run:
   ```bash
   python run.py api
   ```
   This starts the FastAPI server that handles the model predictions and explanations.

3. **Start the Streamlit App**
   Open a second terminal (keep the API terminal running) and run:
   ```bash
   streamlit run streamlit_app.py
   ```

4. **Open the Admin Dashboard**
   In your browser, go to:
   ```
   http://localhost/smartDetector/app/admin/
   ```
   This opens the live fraud monitoring dashboard.

5. **Open the SimplePay App**
   In a new browser tab, go to:
   ```
   http://localhost/smartDetector/app
   ```
   This opens the sandbox payment app (mobile view).

6. **Test the System**
   On the SimplePay app, create an account and perform a few transactions (deposits, withdrawals or sending money). Each transaction is scored by the model in real time and appears on the live admin dashboard, with flagged transactions showing a risk score and SHAP-based explanation.

## Notes

- Both terminals (API and Streamlit) need to stay open while you're testing.
- XAMPP must be running before you open either the admin dashboard or the SimplePay app, since both depend on the PHP backend and MySQL database.

## Team

- Kwakye Addai Solomon Carlos
- Christian Boakye
- Agbo Eyiram Asare

**Supervisor:** Dr. Peter Nimbe
**Department:** Computer Science and Informatics, University of Energy and Natural Resources (UENR)
