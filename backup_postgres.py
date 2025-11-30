import os
import subprocess
import datetime
from pathlib import Path

# Configuration
DB_NAME = "khalifa_db"
DB_USER = "postgres"
DB_PASSWORD = "abdoreda12"
DB_HOST = "localhost"
DB_PORT = "5432"
BACKUP_DIR = "Database_Postgre"

def find_pg_dump():
    # Check if in PATH
    try:
        subprocess.run(["pg_dump", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return "pg_dump"
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Check common paths
    common_paths = [
        r"C:\Program Files\PostgreSQL\17\bin\pg_dump.exe",
        r"C:\Program Files\PostgreSQL\16\bin\pg_dump.exe",
        r"C:\Program Files\PostgreSQL\15\bin\pg_dump.exe",
        r"C:\Program Files\PostgreSQL\14\bin\pg_dump.exe",
        r"C:\Program Files\PostgreSQL\13\bin\pg_dump.exe",
        r"C:\Program Files\PostgreSQL\12\bin\pg_dump.exe",
        r"C:\Program Files (x86)\PostgreSQL\17\bin\pg_dump.exe",
        r"C:\Program Files (x86)\PostgreSQL\16\bin\pg_dump.exe",
        r"C:\Program Files (x86)\PostgreSQL\15\bin\pg_dump.exe",
    ]

    for path in common_paths:
        if os.path.exists(path):
            return path
            
    # Try to find using where command
    try:
        result = subprocess.run(["where", "/r", "C:\\", "pg_dump.exe"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            paths = result.stdout.strip().split('\n')
            if paths:
                return paths[0]
    except Exception:
        pass

    return None

def backup_database():
    # Create backup directory
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
        print(f"Created directory: {BACKUP_DIR}")
    
    pg_dump_path = find_pg_dump()
    
    if not pg_dump_path:
        print("Error: pg_dump.exe not found. Please ensure PostgreSQL is installed and added to PATH.")
        print("Or update the script with the correct path to pg_dump.exe")
        return

    print(f"Using pg_dump from: {pg_dump_path}")

    # Generate filename with timestamp
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(BACKUP_DIR, f"{DB_NAME}_backup_{timestamp}.sql")

    # Set password environment variable
    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASSWORD

    # Construct command
    cmd = [
        pg_dump_path,
        "-h", DB_HOST,
        "-p", DB_PORT,
        "-U", DB_USER,
        "-F", "p",  # Plain text format (SQL)
        "-f", backup_file,
        DB_NAME
    ]

    print(f"Starting backup of {DB_NAME} to {backup_file}...")
    
    try:
        subprocess.run(cmd, env=env, check=True)
        print("Backup completed successfully!")
        print(f"Backup saved to: {os.path.abspath(backup_file)}")
    except subprocess.CalledProcessError as e:
        print(f"Error during backup: {e}")

if __name__ == "__main__":
    backup_database()
