from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
import bcrypt
from utils.db import get_db_connection, rows_to_dicts, dict_from_row

users_bp = Blueprint('users', __name__)


@users_bp.route('/bookmarks', methods=['GET'])
@jwt_required()
def get_bookmarks():
    claims = get_jwt()
    role_id = claims.get('role_id')
    user_id = get_jwt_identity()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        visibility_clause = ""
        params = [user_id]
        if role_id != 1:
            visibility_clause = "AND (COALESCE(pr.flagged, 0) = 0 OR p.uploaded_by = ?)"
            params.append(user_id)

        cursor.execute(f"""
            SELECT p.paper_id, p.title, p.abstract, p.publication_year,
                   STRING_AGG(a.author_name, ', ') AS authors
            FROM Bookmarks b
            JOIN Papers p ON b.paper_id = p.paper_id
            LEFT JOIN PlagiarismReports pr ON p.paper_id = pr.paper_id
            LEFT JOIN Paper_Authors pa ON p.paper_id = pa.paper_id
            LEFT JOIN Authors a ON pa.author_id = a.author_id
            WHERE b.user_id = ?
            {visibility_clause}
            GROUP BY p.paper_id, p.title, p.abstract, p.publication_year
        """, params)
        return jsonify(rows_to_dicts(cursor.fetchall(), cursor))
    finally:
        conn.close()


@users_bp.route('/bookmarks/<int:paper_id>', methods=['POST'])
@jwt_required()
def add_bookmark(paper_id):
    claims = get_jwt()
    role_id = claims.get('role_id')
    user_id = get_jwt_identity()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT p.uploaded_by, COALESCE(pr.flagged, 0) AS flagged
               FROM Papers p
               LEFT JOIN PlagiarismReports pr ON p.paper_id = pr.paper_id
               WHERE p.paper_id = ?""",
            (paper_id,)
        )
        paper_row = cursor.fetchone()
        if not paper_row:
            return jsonify({'error': 'Paper not found'}), 404

        uploaded_by, flagged = paper_row
        if flagged and role_id != 1 and str(uploaded_by) != str(user_id):
            return jsonify({'error': 'This paper is under plagiarism review and is not visible yet.'}), 403

        cursor.execute("SELECT 1 FROM Bookmarks WHERE user_id=? AND paper_id=?", (user_id, paper_id))
        if cursor.fetchone():
            return jsonify({'message': 'Already bookmarked'})

        cursor.execute("INSERT INTO Bookmarks (user_id, paper_id) VALUES (?, ?)", (user_id, paper_id))
        cursor.execute(
            "INSERT INTO UserActivity (user_id, paper_id, activity_type) VALUES (?, ?, 'BOOKMARK')",
            (user_id, paper_id)
        )
        conn.commit()
        return jsonify({'message': 'Bookmarked'})
    finally:
        conn.close()


@users_bp.route('/bookmarks/<int:paper_id>', methods=['DELETE'])
@jwt_required()
def remove_bookmark(paper_id):
    user_id = get_jwt_identity()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM Bookmarks WHERE user_id=? AND paper_id=?", (user_id, paper_id))
        cursor.execute(
            "INSERT INTO UserActivity (user_id, paper_id, activity_type) VALUES (?, ?, 'UNBOOKMARK')",
            (user_id, paper_id)
        )
        conn.commit()
        return jsonify({'message': 'Bookmark removed'})
    finally:
        conn.close()


@users_bp.route('/activity', methods=['GET'])
@jwt_required()
def get_activity():
    claims = get_jwt()
    role_id = claims.get('role_id')
    user_id = get_jwt_identity()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        visibility_clause = ""
        params = [user_id]
        if role_id != 1:
            visibility_clause = "AND (p.paper_id IS NULL OR COALESCE(pr.flagged, 0) = 0 OR p.uploaded_by = ?)"
            params.append(user_id)

        cursor.execute(f"""
            SELECT ua.activity_id, ua.activity_type, ua.activity_date,
                   p.paper_id, p.title
            FROM UserActivity ua
            LEFT JOIN Papers p ON ua.paper_id = p.paper_id
            LEFT JOIN PlagiarismReports pr ON p.paper_id = pr.paper_id
            WHERE ua.user_id = ?
            {visibility_clause}
            ORDER BY ua.activity_date DESC
        """, params)
        return jsonify(rows_to_dicts(cursor.fetchall(), cursor))
    finally:
        conn.close()


@users_bp.route('/stats', methods=['GET'])
@jwt_required()
def get_user_stats():
    claims = get_jwt()
    role_id = claims.get('role_id')
    user_id = get_jwt_identity()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        stats = {'total_views': 0, 'total_downloads': 0}
        if role_id == 2:
            cursor.execute(
                """
                SELECT SUM(ps.views), SUM(ps.downloads)
                FROM Paper_Statistics ps
                JOIN Papers p ON ps.paper_id = p.paper_id
                WHERE p.uploaded_by = ?
                """,
                (user_id,)
            )
            row = cursor.fetchone()
            stats['total_views'] = row[0] or 0
            stats['total_downloads'] = row[1] or 0
        return jsonify(stats)
    finally:
        conn.close()


@users_bp.route('/profile', methods=['GET'])
@jwt_required()
def get_profile():
    user_id = get_jwt_identity()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT u.user_id, u.name, u.email, u.role_id, r.role_name,
                   u.institution_id, i.name AS institution_name, i.location AS institution_location
            FROM Users u
            JOIN Roles r ON u.role_id = r.role_id
            LEFT JOIN Institutions i ON u.institution_id = i.institution_id
            WHERE u.user_id = ?
            """,
            (user_id,)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'User not found'}), 404
        return jsonify(dict_from_row(row, cursor))
    finally:
        conn.close()


@users_bp.route('/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}

    name = data.get('name')
    email = data.get('email')
    institution_id = data.get('institution_id', None)
    current_password = data.get('current_password')
    new_password = data.get('new_password')

    if isinstance(name, str):
        name = name.strip()
    if isinstance(email, str):
        email = email.strip().lower()

    if institution_id in ('', None):
        institution_id = None
    elif institution_id is not None:
        try:
            institution_id = int(institution_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid institution selection'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name, email, password_hash FROM Users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'User not found'}), 404

        current_name, current_email, password_hash = row
        updates = []
        params = []

        if name is not None:
            if not name:
                return jsonify({'error': 'Name cannot be empty'}), 400
            if name != current_name:
                updates.append('name = ?')
                params.append(name)

        if email is not None:
            if not email:
                return jsonify({'error': 'Email cannot be empty'}), 400
            if email != current_email:
                cursor.execute("SELECT user_id FROM Users WHERE email = ?", (email,))
                existing = cursor.fetchone()
                if existing and str(existing[0]) != str(user_id):
                    return jsonify({'error': 'Email already registered'}), 409
                updates.append('email = ?')
                params.append(email)

        if 'institution_id' in data:
            updates.append('institution_id = ?')
            params.append(institution_id)

        if new_password or current_password:
            if not current_password or not new_password:
                return jsonify({'error': 'Current and new passwords are required'}), 400
            if len(new_password) < 6:
                return jsonify({'error': 'New password must be at least 6 characters'}), 400

            try:
                password_ok = bcrypt.checkpw(current_password.encode('utf-8'), password_hash.encode('utf-8'))
            except (ValueError, TypeError):
                return jsonify({'error': 'Current password is invalid'}), 400

            if not password_ok:
                return jsonify({'error': 'Current password is invalid'}), 400

            new_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            updates.append('password_hash = ?')
            params.append(new_hash)

        if not updates:
            return jsonify({'error': 'No changes submitted'}), 400

        params.append(user_id)
        cursor.execute(f"UPDATE Users SET {', '.join(updates)} WHERE user_id = ?", params)
        conn.commit()

        cursor.execute(
            """
            SELECT u.user_id, u.name, u.email, u.role_id, r.role_name,
                   u.institution_id, i.name AS institution_name, i.location AS institution_location
            FROM Users u
            JOIN Roles r ON u.role_id = r.role_id
            LEFT JOIN Institutions i ON u.institution_id = i.institution_id
            WHERE u.user_id = ?
            """,
            (user_id,)
        )
        updated = dict_from_row(cursor.fetchone(), cursor)
        return jsonify({'message': 'Profile updated', 'user': updated})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@users_bp.route('/institutions', methods=['GET'])
def list_institutions():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT institution_id, name, location FROM Institutions ORDER BY name")
        return jsonify(rows_to_dicts(cursor.fetchall(), cursor))

    except ConnectionError:
        return jsonify({'error': 'Database is unavailable. Please try again later.'}), 503
    except Exception:
        return jsonify({'error': 'Failed to load institutions.'}), 500
    finally:
        if conn:
            conn.close()


@users_bp.route('/institutions', methods=['POST'])
def create_institution():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    location = (data.get('location') or '').strip()

    if not name:
        return jsonify({'error': 'Institution name is required'}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT institution_id, name, location FROM Institutions WHERE LOWER(name) = LOWER(?)",
            (name,)
        )
        existing = cursor.fetchone()
        if existing:
            return jsonify(dict_from_row(existing, cursor))

        cursor.execute(
            """
            INSERT INTO Institutions (name, location)
            OUTPUT INSERTED.institution_id, INSERTED.name, INSERTED.location
            VALUES (?, ?)
            """,
            (name, location or None)
        )
        row = cursor.fetchone()
        conn.commit()
        return jsonify(dict_from_row(row, cursor)), 201

    except ConnectionError:
        return jsonify({'error': 'Database is unavailable. Please try again later.'}), 503
    except Exception:
        if conn:
            conn.rollback()
        return jsonify({'error': 'Failed to add institution.'}), 500
    finally:
        if conn:
            conn.close()
