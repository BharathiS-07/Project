from flask import Flask, render_template, request, session, redirect, url_for, jsonify, flash, send_file
import mysql.connector
from model.predict import predict_sepsis_risk
import os
import datetime
import pandas as pd
from functools import wraps
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import letter

app = Flask(__name__)
app.secret_key = 'hospital_grade_sepsis_key_2024'

# --- MySQL Configuration ---
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'Bharathi@07',
    'database': 'sepsis_system'
}

UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def get_db_connection():
    """Returns a MySQL connection with dictionary cursor support."""
    conn = mysql.connector.connect(**DB_CONFIG)
    return conn

# ---------------- HELPERS ----------------

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'doctor' not in session:
            flash("Authorization required. Please log in.", "danger")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ---------------- ROUTES ----------------

@app.route("/", methods=["GET", "POST"])
def login():
    if 'doctor' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM doctors WHERE username=%s AND password=%s", (username, password))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            session['doctor'] = user['username']
            session['doctor_name'] = user['full_name']
            flash(f"Access Granted: Dr. {user['full_name']}", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Authentication Failed. Invalid credentials.", "danger")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for('login'))

@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Total Patients Count
    cursor.execute("SELECT COUNT(*) as count FROM patients")
    total_patients = cursor.fetchone()['count']
    
    # Risk Breakdown for latest records of each patient
    cursor.execute("""
        SELECT risk_level, COUNT(*) as count 
        FROM patient_records r
        JOIN (SELECT patient_id, MAX(record_time) as max_time FROM patient_records GROUP BY patient_id) latest
        ON r.patient_id = latest.patient_id AND r.record_time = latest.max_time
        GROUP BY risk_level
    """)
    risk_counts = cursor.fetchall()
    
    breakdown = {"High Risk": 0, "Medium Risk": 0, "Low Risk": 0}
    for row in risk_counts:
        level = row['risk_level']
        if level in breakdown: breakdown[level] = row['count']
    
    # Recent ACTIVE high-risk alerts (only latest record per patient)
    cursor.execute("""
        SELECT p.name, p.infection_source, r.risk_score, r.risk_level, r.record_time, p.patient_id
        FROM patient_records r
        JOIN patients p ON r.patient_id = p.patient_id
        JOIN (
            SELECT patient_id, MAX(record_time) as max_time
            FROM patient_records
            GROUP BY patient_id
        ) latest
        ON r.patient_id = latest.patient_id AND r.record_time = latest.max_time
        WHERE r.risk_level = 'High Risk'
        ORDER BY r.record_time DESC
        LIMIT 5
    """)
    alerts = cursor.fetchall()

    for a in alerts:
        if a["record_time"]:
            a["record_time"] = a["record_time"].strftime("%Y-%m-%d %H:%M:%S")

    conn.close()
    
    return render_template("dashboard.html", 
                         doctor=session.get('doctor_name', 'Doctor'),
                         context_date=datetime.date.today().strftime('%B %d, %Y'),
                         total_patients=total_patients,
                         breakdown=breakdown,
                         alerts=alerts)

@app.route("/api/dashboard_data")
@login_required
def dashboard_data():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Total Patients
    cursor.execute("SELECT COUNT(*) as count FROM patients")
    total_patients = cursor.fetchone()['count']

    # Risk Breakdown
    cursor.execute("""
        SELECT risk_level, COUNT(*) as count 
        FROM patient_records r
        JOIN (
            SELECT patient_id, MAX(record_time) as max_time
            FROM patient_records
            GROUP BY patient_id
        ) latest
        ON r.patient_id = latest.patient_id AND r.record_time = latest.max_time
        GROUP BY risk_level
    """)
    risk_counts = cursor.fetchall()

    breakdown = {"High Risk": 0, "Medium Risk": 0, "Low Risk": 0}
    for row in risk_counts:
        if row['risk_level'] in breakdown:
            breakdown[row['risk_level']] = row['count']

    # Recent alerts
    cursor.execute("""
        SELECT p.name, p.infection_source, r.risk_score, r.risk_level, r.record_time, p.patient_id
        FROM patient_records r
        JOIN patients p ON r.patient_id = p.patient_id
        JOIN (
            SELECT patient_id, MAX(record_time) as max_time
            FROM patient_records
            GROUP BY patient_id
        ) latest
        ON r.patient_id = latest.patient_id AND r.record_time = latest.max_time
        WHERE r.risk_level = 'High Risk'
        ORDER BY r.record_time DESC
        LIMIT 5
    """)

    alerts = cursor.fetchall()

    # ⭐ FIX → convert datetime to string
    for a in alerts:
        a["record_time"] = a["record_time"].isoformat()

    conn.close()

    return jsonify({
        "alerts": alerts,
        "total_patients": total_patients,
        "breakdown": breakdown
    })


@app.route("/register_patient", methods=["GET", "POST"])
@login_required
def register_patient():
    if request.method == "POST":
        name = request.form.get("name")
        age = request.form.get("age")
        gender = request.form.get("gender")
        icu = request.form.get("icu_details")
        infection = request.form.get("infection_source")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO patients (name, age, gender, icu_details, infection_source) VALUES (%s, %s, %s, %s, %s)",
            (name, age, gender, icu, infection)
        )
        conn.commit()
        pid = cursor.lastrowid
        conn.close()
        flash(f"Patient {name} Registered. ID: {pid}", "success")
        return redirect(url_for('dashboard'))
            
    return render_template("register.html")

@app.route("/patient", methods=["GET", "POST"])
@login_required
def patient_assessment():
    result = None
    patient = None
    prefill = {} # SOLUTION: Prevent UndefinedError
    
    patient_id = request.args.get("patient_id") or request.form.get("patient_id")
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if patient_id:
        cursor.execute("SELECT * FROM patients WHERE patient_id=%s", (patient_id,))
        patient = cursor.fetchone()

    if request.method == "POST":
        if patient:
            # Capture inputs to send back to template (so they stay in the text boxes)
            prefill = request.form.to_dict()
            
            # Prepare data for AI model
            model_input = prefill.copy()
            model_input.update({'Age': patient['age'], 'Gender': patient['gender']})
            
            # Call your ML prediction logic
            pred = predict_sepsis_risk(model_input) 
            
            def to_float(value):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
            
            # Save the record
            # Check if record already exists
            cursor.execute("""
                SELECT record_id FROM patient_records 
                WHERE patient_id=%s
                ORDER BY record_time DESC
                LIMIT 1
                """, (patient_id,))

            existing = cursor.fetchone()

            if existing:
                    # UPDATE existing record
                    cursor.execute("""
                        UPDATE patient_records
                        SET HR=%s, O2Sat=%s, Temp=%s, SBP=%s, MAP=%s, DBP=%s, Resp=%s,
                            Lactate=%s, WBC=%s, Creatinine=%s, Platelets=%s, ICULOS=%s,
                            risk_score=%s, risk_level=%s, explanation=%s
                        WHERE record_id=%s
                    """, (
                        to_float(prefill.get("HR")),
                        to_float(prefill.get("O2Sat")),
                        to_float(prefill.get("Temp")),
                        to_float(prefill.get("SBP")),
                        to_float(prefill.get("MAP")),
                        to_float(prefill.get("DBP")),
                        to_float(prefill.get("Resp")),
                        to_float(prefill.get("Lactate")),
                        to_float(prefill.get("WBC")),
                        to_float(prefill.get("Creatinine")),
                        to_float(prefill.get("Platelets")),
                        int(prefill.get("ICULOS", 1)),
                        pred['score'],
                        pred['risk_level'],
                        pred['explanation'],
                        existing['record_id']
                    ))

            else:
                    # INSERT new record
                    cursor.execute("""
                        INSERT INTO patient_records 
                        (patient_id, HR, O2Sat, Temp, SBP, MAP, DBP, Resp, Lactate, WBC,
                        Creatinine, Platelets, ICULOS, risk_score, risk_level, explanation)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (
                        patient_id,
                        to_float(prefill.get("HR")),
                        to_float(prefill.get("O2Sat")),
                        to_float(prefill.get("Temp")),
                        to_float(prefill.get("SBP")),
                        to_float(prefill.get("MAP")),
                        to_float(prefill.get("DBP")),
                        to_float(prefill.get("Resp")),
                        to_float(prefill.get("Lactate")),
                        to_float(prefill.get("WBC")),
                        to_float(prefill.get("Creatinine")),
                        to_float(prefill.get("Platelets")),
                        int(prefill.get("ICULOS", 1)),
                        pred['score'],
                        pred['risk_level'],
                        pred['explanation']
                    ))

            conn.commit()
            result = pred
        else:
            flash("Patient ID required to run analysis.", "warning")

    conn.close()
    # Always pass prefill, even if it's an empty dictionary
    return render_template("patient.html", result=result, patient=patient, prefill=prefill)

@app.route("/patient_data/<int:patient_id>")
@login_required
def patient_data_json(patient_id):
    """API endpoint for Chart.js in the patient assessment page."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT risk_score, record_time 
        FROM patient_records 
        WHERE patient_id=%s 
        ORDER BY record_time ASC
    """, (patient_id,))
    data = cursor.fetchall()
    conn.close()
    
    return jsonify({
        "labels": [row['record_time'].isoformat() for row in data],
        "scores": [row['risk_score'] for row in data]
    })
@app.route("/analytics")
@login_required
def analytics():
    patient_id = request.args.get("patient_id")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    patient = None
    history = []
    
    if patient_id:
        cursor.execute("SELECT * FROM patients WHERE patient_id=%s", (patient_id,))
        patient = cursor.fetchone()
        if patient:
            # Format record_time directly in the SQL query
            cursor.execute("""
                SELECT risk_score, risk_level, 
                       DATE_FORMAT(record_time, '%Y-%m-%d %H:%i') as record_time, 
                       Temp, HR, O2Sat, WBC, explanation
                FROM patient_records WHERE patient_id=%s ORDER BY record_time ASC
            """, (patient_id,))
            history = cursor.fetchall()
    
    conn.close()
    return render_template("analytics.html", patient=patient, history=history, search_id=patient_id)


@app.route("/download_report/<int:patient_id>")
@login_required
def download_report(patient_id):

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Patient details
    cursor.execute("SELECT * FROM patients WHERE patient_id=%s", (patient_id,))
    patient = cursor.fetchone()

    # Patient records
    cursor.execute("""
        SELECT risk_score, risk_level, Temp, HR, O2Sat, WBC, record_time
        FROM patient_records
        WHERE patient_id=%s
        ORDER BY record_time DESC
    """, (patient_id,))
    
    records = cursor.fetchall()
    conn.close()

    file_path = f"report_patient_{patient_id}.pdf"

    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Hospital Sepsis Risk Report", styles['Title']))
    elements.append(Spacer(1,20))

    elements.append(Paragraph(f"Patient Name: {patient['name']}", styles['Normal']))
    elements.append(Paragraph(f"Age: {patient['age']}", styles['Normal']))
    elements.append(Paragraph(f"Gender: {patient['gender']}", styles['Normal']))
    elements.append(Spacer(1,20))

    data = [["Time","Risk Score","Risk Level","Temp","HR","O2Sat","WBC"]]

    for r in records:
        data.append([
            str(r["record_time"]),
            f"{r['risk_score']}%",
            r["risk_level"],
            r["Temp"],
            r["HR"],
            r["O2Sat"],
            r["WBC"]
        ])

    table = Table(data)
    elements.append(table)

    pdf = SimpleDocTemplate(file_path, pagesize=letter)
    pdf.build(elements)

    return send_file(file_path, as_attachment=True)



@app.route('/patients')
@login_required
def patients_list():
    search_query = request.args.get('search', '')
    filter_type = request.args.get('filter', 'all')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    query = """
    SELECT p.*, pr.risk_level, pr.risk_score
    FROM patients p
    LEFT JOIN patient_records pr
        ON p.patient_id = pr.patient_id
        AND pr.record_time = (
            SELECT MAX(pr2.record_time)
            FROM patient_records pr2
            WHERE pr2.patient_id = p.patient_id
        )
    """

    filters = []
    values = []

    # 🔎 Patient ID Search
    if search_query:
        filters.append("p.patient_id = %s")
        values.append(search_query)

    # 🔥 Risk filter
    if filter_type == 'high':
        filters.append("pr.risk_level = 'High Risk'")
    elif filter_type == 'medium':
        filters.append("pr.risk_level = 'Medium Risk'")
    elif filter_type == 'low':
        filters.append("pr.risk_level = 'Low Risk'")

    # Apply filters properly
    if filters:
        query += " WHERE " + " AND ".join(filters)

    cursor.execute(query, values)
    patients = cursor.fetchall()
    conn.close()

    return render_template(
        'patients_list.html',
        patients=patients,
        search_query=search_query,
        filter_type=filter_type
    )
    
if __name__ == "__main__":
    app.run(debug=True, port=5000)

    