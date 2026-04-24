from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
import bcrypt
from utils.db import get_db_connection, dict_from_row

auth_bp = Blueprint('auth', __name__)

VALID_ROLES = {1: 'Admin', 2: 'Researcher', 3: 'Student'}

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    role_id = data.get('role_id')
    institution_id = data.get('institution_id')

    if not all([name, email, password, role_id]):
        return jsonify({'error': 'All fields are required'}), 400

    if role_id not in VALID_ROLES:
        return jsonify({'error': 'Invalid role. Use 1 (Admin), 2 (Researcher), or 3 (Student)'}), 400

    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    # Hash password
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check email uniqueness
        cursor.execute("SELECT user_id FROM Users WHERE email = ?", (email,))
        if cursor.fetchone():
            return jsonify({'error': 'Email already registered'}), 409

        # Insert user
        cursor.execute(
            """INSERT INTO Users (name, email, password_hash, role_id, institution_id)
               OUTPUT INSERTED.user_id
               VALUES (?, ?, ?, ?, ?)""",
            (name, email, password_hash, role_id, institution_id)
        )
        user_id = cursor.fetchone()[0]
        conn.commit()

        token = create_access_token(
            identity=str(user_id),
            additional_claims={'role_id': role_id, 'name': name, 'email': email}
        )
        return jsonify({
            'message': 'Registration successful',
            'token': token,
            'user': {'user_id': user_id, 'name': name, 'email': email, 'role_id': role_id}
        }), 201

    except ConnectionError:
        return jsonify({'error': 'Database is unavailable. Please try again later.'}), 503
    except Exception:
        if conn:
            conn.rollback()
        return jsonify({'error': 'Registration failed. Please try again.'}), 500
    finally:
        if conn:
            conn.close()


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """SELECT u.user_id, u.name, u.email, u.password_hash, u.role_id,
                      r.role_name, u.institution_id, i.name as institution_name
               FROM Users u
               JOIN Roles r ON u.role_id = r.role_id
               LEFT JOIN Institutions i ON u.institution_id = i.institution_id
               WHERE u.email = ?""",
            (email,)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Invalid credentials'}), 401

        user = dict_from_row(row, cursor)

        try:
            password_ok = bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8'))
        except (ValueError, TypeError):
            return jsonify({'error': 'This account password needs reset. Please register a new account.'}), 401

        if not password_ok:
            return jsonify({'error': 'Invalid credentials'}), 401

        token = create_access_token(
            identity=str(user['user_id']),
            additional_claims={
                'role_id': user['role_id'],
                'name': user['name'],
                'email': user['email']
            }
        )
        return jsonify({
            'message': 'Login successful',
            'token': token,
            'user': {
                'user_id': user['user_id'],
                'name': user['name'],
                'email': user['email'],
                'role_id': user['role_id'],
                'role_name': user['role_name'],
                'institution_name': user['institution_name']
            }
        })

    except ConnectionError:
        return jsonify({'error': 'Database is unavailable. Please try again later.'}), 503
    except Exception:
        return jsonify({'error': 'Login failed. Please try again.'}), 500
    finally:
        if conn:
            conn.close()


@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_me():
    user_id = get_jwt_identity()
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """SELECT u.user_id, u.name, u.email, u.role_id, r.role_name,
                      i.name as institution_name
               FROM Users u
               JOIN Roles r ON u.role_id = r.role_id
               LEFT JOIN Institutions i ON u.institution_id = i.institution_id
               WHERE u.user_id = ?""",
            (user_id,)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'User not found'}), 404
        user = dict_from_row(row, cursor)
        return jsonify(user)

    except ConnectionError:
        return jsonify({'error': 'Database is unavailable. Please try again later.'}), 503
    except Exception:
        return jsonify({'error': 'Failed to load user profile.'}), 500
    finally:
        if conn:
            conn.close()
