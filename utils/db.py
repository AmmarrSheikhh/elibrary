import pyodbc
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env', override=True)

def get_db_connection():
    """Get a connection to the SQL Server database."""
    driver = os.getenv('DB_DRIVER', 'ODBC Driver 17 for SQL Server')
    server = os.getenv('DB_SERVER', 'localhost\\SQLEXPRESS')
    database = os.getenv('DB_NAME', 'ELIB2')
    auth_mode = os.getenv('DB_AUTH', 'integrated').strip().lower()
    timeout = os.getenv('DB_TIMEOUT', '5')

    connection_parts = [
        f"DRIVER={{{driver}}};",
        f"SERVER={server};",
        f"DATABASE={database};",
        "TrustServerCertificate=yes;",
        f"Connection Timeout={timeout};",
    ]

    if auth_mode == 'sql':
        user = os.getenv('DB_USER', '').strip()
        password = os.getenv('DB_PASSWORD', '')
        if not user or not password:
            raise ConnectionError("DB_USER and DB_PASSWORD are required when DB_AUTH=sql")
        connection_parts.append(f"UID={user};")
        connection_parts.append(f"PWD={password};")
    else:
        connection_parts.append("Trusted_Connection=yes;")

    connection_string = ''.join(connection_parts)

    try:
        return pyodbc.connect(connection_string)
    except pyodbc.Error as exc:
        raise ConnectionError("Database connection failed") from exc

def dict_from_row(row, cursor):
    """Convert a pyodbc Row to a dictionary."""
    if row is None:
        return None
    columns = [column[0] for column in cursor.description]
    return dict(zip(columns, row))

def rows_to_dicts(rows, cursor):
    """Convert a list of pyodbc Rows to a list of dicts."""
    if not rows:
        return []
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in rows]
