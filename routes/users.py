from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from utils.db import get_db_connection, rows_to_dicts

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
