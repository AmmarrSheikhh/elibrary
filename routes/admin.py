from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from utils.db import get_db_connection, rows_to_dicts, dict_from_row
from utils.plagiarism import find_best_match

admin_bp = Blueprint('admin', __name__)


def require_admin():
    from functools import wraps
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            claims = get_jwt()
            if claims.get('role_id') != 1:
                return jsonify({'error': 'Admin access required'}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


def delete_paper_cascade(cursor, paper_id):
    for table in [
        'UserActivity',
        'Bookmarks',
        'Reviews',
        'Paper_Statistics',
        'PlagiarismReports',
        'Paper_Authors',
        'Paper_Categories',
    ]:
        cursor.execute(f"DELETE FROM {table} WHERE paper_id = ?", (paper_id,))

    cursor.execute(
        "DELETE FROM Citations WHERE citing_paper_id = ? OR cited_paper_id = ?",
        (paper_id, paper_id)
    )
    cursor.execute("DELETE FROM Papers WHERE paper_id = ?", (paper_id,))


def fetch_paper_summary(cursor, paper_id):
    cursor.execute(
        """
        SELECT p.paper_id, p.title, p.abstract, p.publication_year,
               p.upload_date, u.name AS uploader_name
        FROM Papers p
        LEFT JOIN Users u ON p.uploaded_by = u.user_id
        WHERE p.paper_id = ?
        """,
        (paper_id,)
    )
    row = cursor.fetchone()
    if not row:
        return None

    paper = dict_from_row(row, cursor)

    cursor.execute(
        """
        SELECT a.author_id, a.author_name, a.affiliation
        FROM Authors a
        JOIN Paper_Authors pa ON a.author_id = pa.author_id
        WHERE pa.paper_id = ?
        """,
        (paper_id,)
    )
    paper['authors'] = rows_to_dicts(cursor.fetchall(), cursor)

    cursor.execute(
        """
        SELECT c.category_id, c.category_name, c.description
        FROM Categories c
        JOIN Paper_Categories pc ON c.category_id = pc.category_id
        WHERE pc.paper_id = ?
        """,
        (paper_id,)
    )
    paper['categories'] = rows_to_dicts(cursor.fetchall(), cursor)

    return paper


@admin_bp.route('/users', methods=['GET'])
@jwt_required()
@require_admin()
def list_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        role_param = (request.args.get('role') or '').strip().lower()
        search = (request.args.get('q') or '').strip()

        role_map = {'admin': 1, 'researcher': 2, 'student': 3}
        role_id = None
        if role_param and role_param != 'all':
            if role_param.isdigit():
                role_id = int(role_param)
            else:
                role_id = role_map.get(role_param)

        conditions = []
        params = []
        if role_id:
            conditions.append("u.role_id = ?")
            params.append(role_id)
        if search:
            conditions.append("(u.name LIKE ? OR u.email LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        cursor.execute(f"""
            SELECT u.user_id, u.name, u.email, u.role_id, r.role_name,
                   i.name AS institution_name
            FROM Users u
            JOIN Roles r ON u.role_id = r.role_id
            LEFT JOIN Institutions i ON u.institution_id = i.institution_id
            {where_clause}
            ORDER BY u.user_id
        """, params)
        return jsonify(rows_to_dicts(cursor.fetchall(), cursor))
    finally:
        conn.close()


@admin_bp.route('/users/<int:user_id>', methods=['DELETE'])
@jwt_required()
@require_admin()
def delete_user(user_id):
    admin_user_id = get_jwt_identity()
    if str(admin_user_id) == str(user_id):
        return jsonify({'error': 'You cannot delete your own account'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id FROM Users WHERE user_id = ?", (user_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'User not found'}), 404

        # Remove all papers uploaded by this user first so researchers/admins are deletable.
        cursor.execute("SELECT paper_id FROM Papers WHERE uploaded_by = ?", (user_id,))
        uploaded_papers = [row[0] for row in cursor.fetchall()]
        for paper_id in uploaded_papers:
            delete_paper_cascade(cursor, paper_id)

        cursor.execute("DELETE FROM UserActivity WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM Bookmarks WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM Reviews WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM Users WHERE user_id = ?", (user_id,))
        cursor.execute(
            "INSERT INTO UserActivity (user_id, paper_id, activity_type) VALUES (?, ?, 'DELETE_USER')",
            (admin_user_id, None)
        )
        conn.commit()
        return jsonify({'message': 'User deleted'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@admin_bp.route('/plagiarism', methods=['GET'])
@jwt_required()
@require_admin()
def get_plagiarism_reports():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        flagged_only = request.args.get('flagged', 'false').lower() == 'true'
        where = "WHERE pr.flagged = 1" if flagged_only else ""
        cursor.execute(f"""
            SELECT pr.report_id, pr.paper_id, pr.similarity_score, pr.flagged,
                   p.title, u.name AS uploaded_by
                   ,p.abstract
            FROM PlagiarismReports pr
            JOIN Papers p ON pr.paper_id = p.paper_id
            JOIN Users u ON p.uploaded_by = u.user_id
            {where}
            ORDER BY pr.similarity_score DESC
        """)
        reports = rows_to_dicts(cursor.fetchall(), cursor)

        cursor.execute("SELECT paper_id, title, abstract FROM Papers WHERE abstract IS NOT NULL")
        candidates = rows_to_dicts(cursor.fetchall(), cursor)

        for report in reports:
            best_match = find_best_match(report['paper_id'], report.get('abstract'), candidates)
            report['matched_paper_id'] = best_match['paper_id'] if best_match else None
            report['matched_paper_title'] = best_match['title'] if best_match else None
            report['matched_similarity_score'] = best_match['similarity_score'] if best_match else 0.0
            report.pop('abstract', None)

        return jsonify(reports)
    finally:
        conn.close()


@admin_bp.route('/plagiarism/<int:report_id>', methods=['GET'])
@jwt_required()
@require_admin()
def get_plagiarism_report_detail(report_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT report_id, paper_id, similarity_score, flagged FROM PlagiarismReports WHERE report_id = ?",
            (report_id,)
        )
        report_row = cursor.fetchone()
        if not report_row:
            return jsonify({'error': 'Report not found'}), 404

        report = dict_from_row(report_row, cursor)
        paper = fetch_paper_summary(cursor, report['paper_id'])

        cursor.execute("SELECT paper_id, title, abstract FROM Papers WHERE abstract IS NOT NULL")
        candidates = rows_to_dicts(cursor.fetchall(), cursor)
        best_match = find_best_match(report['paper_id'], paper.get('abstract') if paper else '', candidates)

        match = None
        if best_match:
            match = fetch_paper_summary(cursor, best_match['paper_id'])
            if match:
                match['similarity_score'] = best_match['similarity_score']

        return jsonify({
            'report_id': report['report_id'],
            'similarity_score': report['similarity_score'],
            'flagged': bool(report['flagged']),
            'paper': paper,
            'match': match
        })
    finally:
        conn.close()


@admin_bp.route('/plagiarism/<int:report_id>/resolve', methods=['POST'])
@jwt_required()
@require_admin()
def resolve_plagiarism(report_id):
    data = request.get_json(silent=True) or {}
    action = (data.get('action') or 'approve').strip().lower()
    if action not in {'approve', 'reject'}:
        return jsonify({'error': "Invalid action. Use 'approve' or 'reject'."}), 400

    admin_user_id = get_jwt_identity()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT paper_id FROM PlagiarismReports WHERE report_id = ?", (report_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Report not found'}), 404

        paper_id = row[0]

        if action == 'approve':
            cursor.execute(
                "UPDATE PlagiarismReports SET flagged = 0 WHERE report_id = ?",
                (report_id,)
            )
            cursor.execute(
                "INSERT INTO UserActivity (user_id, paper_id, activity_type) VALUES (?, ?, 'PLAGIARISM_APPROVE')",
                (admin_user_id, paper_id)
            )
            message = 'Paper approved and report resolved'
        else:
            delete_paper_cascade(cursor, paper_id)
            cursor.execute(
                "INSERT INTO UserActivity (user_id, paper_id, activity_type) VALUES (?, ?, 'PLAGIARISM_REJECT')",
                (admin_user_id, None)
            )
            message = 'Paper rejected and deleted'

        conn.commit()
        return jsonify({'message': message, 'action': action})
    finally:
        conn.close()


@admin_bp.route('/stats', methods=['GET'])
@jwt_required()
@require_admin()
def get_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        stats = {}
        cursor.execute("SELECT COUNT(*) FROM Papers")
        stats['total_papers'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM Users")
        stats['total_users'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM PlagiarismReports WHERE flagged = 1")
        stats['flagged_reports'] = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(views), SUM(downloads) FROM Paper_Statistics")
        row = cursor.fetchone()
        stats['total_views'] = row[0] or 0
        stats['total_downloads'] = row[1] or 0

        cursor.execute("""
            SELECT TOP 5 p.title, ps.views, ps.downloads
            FROM Paper_Statistics ps JOIN Papers p ON ps.paper_id = p.paper_id
            ORDER BY ps.views DESC
        """)
        stats['top_papers'] = rows_to_dicts(cursor.fetchall(), cursor)

        cursor.execute("""
            SELECT r.role_name, COUNT(u.user_id) as count
            FROM Roles r LEFT JOIN Users u ON r.role_id = u.role_id
            GROUP BY r.role_name
        """)
        stats['users_by_role'] = rows_to_dicts(cursor.fetchall(), cursor)

        return jsonify(stats)
    finally:
        conn.close()
