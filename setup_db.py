import mysql.connector

# DB Configuration
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'Bharathi@07',
    'database': 'sepsis_system'
}

def init_db():
    conn = None
    try:
        # Connect to MySQL Server (no DB selected yet)
        conn = mysql.connector.connect(
            host=DB_CONFIG['host'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password']
        )
        cursor = conn.cursor()

        # Create Database
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['database']}")
        print(f"Database '{DB_CONFIG['database']}' checked/created.")
        
        # Connect to the specific database
        conn.database = DB_CONFIG['database']

        # DROP TABLES (for clean setup) - Remove this in production if needed
        # But required here to fix schema mismatch
        cursor.execute("DROP TABLE IF EXISTS patient_records")
        cursor.execute("DROP TABLE IF EXISTS doctors")
        cursor.execute("DROP TABLE IF EXISTS patients")

        # Create Doctors Table
        cursor.execute("""
            CREATE TABLE doctors (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                full_name VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create Patients Table
        cursor.execute("""
            CREATE TABLE patients (
                patient_id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                age INT NOT NULL,
                gender VARCHAR(10) NOT NULL,
                icu_details VARCHAR(255),
                admission_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                infection_source VARCHAR(100)
            )
        """)

        # Create Vitals/Records Table
        cursor.execute("""
            CREATE TABLE patient_records (
                record_id INT AUTO_INCREMENT PRIMARY KEY,
                patient_id INT,
                HR FLOAT, O2Sat FLOAT, Temp FLOAT, SBP FLOAT, MAP FLOAT, DBP FLOAT, Resp FLOAT,
                Lactate FLOAT, WBC FLOAT, Creatinine FLOAT, Platelets FLOAT, ICULOS INT,
                risk_score FLOAT,
                risk_level VARCHAR(20),
                explanation TEXT,
                record_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (patient_id) REFERENCES patients(patient_id) ON DELETE CASCADE
            )
        """)
        
        # Insert a default doctor
        cursor.execute("INSERT INTO doctors (username, password, full_name) VALUES ('admin', 'admin123', 'Dr. Radhi')")
        print("Default doctor 'admin' created with password 'admin123'.")

        conn.commit()
        print("Database schema reset and initialized successfully.")
        
    except mysql.connector.Error as err:
        print(f"Error: {err}")
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == "__main__":
    init_db()
