from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from utils.db import get_db_connection, dict_from_row, rows_to_dicts
from utils.plagiarism import check_plagiarism, find_best_match

papers_bp = Blueprint('papers', __name__)


def require_role(*role_ids):
    """Decorator to enforce role-based access."""
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*args, **kwargs):
            claims = get_jwt()
            if claims.get('role_id') not in role_ids:
                return jsonify({'error': 'Insufficient permissions'}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


@papers_bp.route('', methods=['GET'])
@jwt_required()
def list_papers():
    """List papers with search/filter support."""
    claims = get_jwt()
    role_id = claims.get('role_id')
    user_id = get_jwt_identity()

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        keyword = request.args.get('keyword', '')
        author = request.args.get('author', '')
        category = request.args.get('category', '')
        year_from = request.args.get('year_from', '')
        year_to = request.args.get('year_to', '')
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(max(1, int(request.args.get('per_page', 10))), 50)
        offset = (page - 1) * per_page
        start_row = offset + 1
        end_row = offset + per_page

        conditions = []
        params = []

        if keyword:
            conditions.append(
                """(
                       p.title LIKE ?
                       OR p.abstract LIKE ?
                       OR EXISTS (
                           SELECT 1
                           FROM Paper_Authors pa_kw
                           JOIN Authors a_kw ON pa_kw.author_id = a_kw.author_id
                           WHERE pa_kw.paper_id = p.paper_id AND a_kw.author_name LIKE ?
                       )
                       OR EXISTS (
                           SELECT 1
                           FROM Paper_Categories pc_kw
                           JOIN Categories c_kw ON pc_kw.category_id = c_kw.category_id
                           WHERE pc_kw.paper_id = p.paper_id AND c_kw.category_name LIKE ?
                       )
                   )"""
            )
            params.extend([f'%{keyword}%', f'%{keyword}%', f'%{keyword}%', f'%{keyword}%'])
        if author:
            conditions.append(
                """EXISTS (
                       SELECT 1
                       FROM Paper_Authors pa_filter
                       JOIN Authors a_filter ON pa_filter.author_id = a_filter.author_id
                       WHERE pa_filter.paper_id = p.paper_id AND a_filter.author_name LIKE ?
                   )"""
            )
            params.append(f'%{author}%')
        if category:
            conditions.append(
                """EXISTS (
                       SELECT 1
                       FROM Paper_Categories pc_filter
                       JOIN Categories c_filter ON pc_filter.category_id = c_filter.category_id
                       WHERE pc_filter.paper_id = p.paper_id AND c_filter.category_name LIKE ?
                   )"""
            )
            params.append(f'%{category}%')
        if year_from:
            conditions.append("p.publication_year >= ?")
            params.append(int(year_from))
        if year_to:
            conditions.append("p.publication_year <= ?")
            params.append(int(year_to))

        # Flagged papers are only visible to uploader and admins until approved.
        if role_id != 1:
            conditions.append("(COALESCE(pr.flagged, 0) = 0 OR p.uploaded_by = ?)")
            params.append(user_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = f"""
            WITH filtered AS (
                SELECT
                    p.paper_id,
                    p.title,
                    p.abstract,
                    p.publication_year,
                    p.upload_date,
                    p.uploaded_by,
                    u.name AS uploader_name,
                    ps.views,
                    ps.downloads,
                    pr.similarity_score,
                    pr.flagged,
                    (
                        SELECT STRING_AGG(a.author_name, ', ')
                        FROM Paper_Authors pa
                        JOIN Authors a ON pa.author_id = a.author_id
                        WHERE pa.paper_id = p.paper_id
                    ) AS authors,
                    (
                        SELECT STRING_AGG(c.category_name, ', ')
                        FROM Paper_Categories pc
                        JOIN Categories c ON pc.category_id = c.category_id
                        WHERE pc.paper_id = p.paper_id
                    ) AS categories,
                    ROW_NUMBER() OVER (ORDER BY p.upload_date DESC, p.paper_id DESC) AS row_num
                FROM Papers p
                LEFT JOIN Users u ON p.uploaded_by = u.user_id
                LEFT JOIN Paper_Statistics ps ON p.paper_id = ps.paper_id
                LEFT JOIN PlagiarismReports pr ON p.paper_id = pr.paper_id
                {where_clause}
            )
            SELECT paper_id, title, abstract, publication_year,
                   upload_date, uploaded_by, uploader_name,
                   views, downloads, similarity_score, flagged,
                   authors, categories
            FROM filtered
            WHERE row_num BETWEEN ? AND ?
            ORDER BY row_num
        """
        query_params = params + [start_row, end_row]
        cursor.execute(query, query_params)
        papers = rows_to_dicts(cursor.fetchall(), cursor)

        # Get total count
        count_query = f"""
            SELECT COUNT(*)
            FROM Papers p
            LEFT JOIN PlagiarismReports pr ON p.paper_id = pr.paper_id
            {where_clause}
        """
        cursor.execute(count_query, params)
        total = cursor.fetchone()[0]

        return jsonify({'papers': papers, 'total': total, 'page': page, 'per_page': per_page})

    except ValueError:
        return jsonify({'error': 'Invalid pagination or year filter value'}), 400
    except Exception:
        return jsonify({'error': 'Failed to fetch papers'}), 500
    finally:
        conn.close()


@papers_bp.route('/top', methods=['GET'])
@jwt_required()
def top_papers():
    """Return top viewed papers for dashboard widgets."""
    claims = get_jwt()
    role_id = claims.get('role_id')
    user_id = get_jwt_identity()
    limit = min(max(int(request.args.get('limit', 5)), 1), 20)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        where_clause = ""
        params = []
        if role_id != 1:
            where_clause = "WHERE COALESCE(pr.flagged, 0) = 0 OR p.uploaded_by = ?"
            params.append(user_id)

        cursor.execute(
            f"""
            SELECT TOP {limit}
                   p.paper_id,
                   p.title,
                   COALESCE(ps.views, 0) AS views,
                   COALESCE(ps.downloads, 0) AS downloads
            FROM Papers p
            LEFT JOIN Paper_Statistics ps ON p.paper_id = ps.paper_id
            LEFT JOIN PlagiarismReports pr ON p.paper_id = pr.paper_id
            {where_clause}
            ORDER BY COALESCE(ps.views, 0) DESC, p.paper_id DESC
            """,
            params,
        )

        return jsonify(rows_to_dicts(cursor.fetchall(), cursor))
    finally:
        conn.close()


@papers_bp.route('/<int:paper_id>', methods=['GET'])
@jwt_required()
def get_paper(paper_id):
    """Get a single paper with full details. Also logs VIEW activity."""
    claims = get_jwt()
    role_id = claims.get('role_id')
    user_id = get_jwt_identity()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT p.paper_id, p.title, p.abstract, p.publication_year,
                   p.upload_date, p.uploaded_by,
                   u.name AS uploader_name,
                   ps.views, ps.downloads,
                   pr.similarity_score, pr.flagged
            FROM Papers p
            LEFT JOIN Users u ON p.uploaded_by = u.user_id
            LEFT JOIN Paper_Statistics ps ON p.paper_id = ps.paper_id
            LEFT JOIN PlagiarismReports pr ON p.paper_id = pr.paper_id
            WHERE p.paper_id = ?
        """, (paper_id,))
        paper = dict_from_row(cursor.fetchone(), cursor)
        if not paper:
            return jsonify({'error': 'Paper not found'}), 404

        if paper.get('flagged') and role_id != 1 and str(paper.get('uploaded_by')) != str(user_id):
            return jsonify({'error': 'This paper is under plagiarism review and is not visible yet.'}), 403

        # Authors
        cursor.execute("""
            SELECT a.author_id, a.author_name, a.affiliation
            FROM Authors a JOIN Paper_Authors pa ON a.author_id = pa.author_id
            WHERE pa.paper_id = ?
        """, (paper_id,))
        paper['authors'] = rows_to_dicts(cursor.fetchall(), cursor)

        # Categories
        cursor.execute("""
            SELECT c.category_id, c.category_name, c.description
            FROM Categories c JOIN Paper_Categories pc ON c.category_id = pc.category_id
            WHERE pc.paper_id = ?
        """, (paper_id,))
        paper['categories'] = rows_to_dicts(cursor.fetchall(), cursor)

        # Citations (papers this one cites)
        cursor.execute("""
            SELECT p.paper_id, p.title, p.publication_year
            FROM Papers p JOIN Citations c ON p.paper_id = c.cited_paper_id
            WHERE c.citing_paper_id = ?
        """, (paper_id,))
        paper['cites'] = rows_to_dicts(cursor.fetchall(), cursor)

        # Cited by (papers that cite this one)
        cursor.execute("""
            SELECT p.paper_id, p.title, p.publication_year
            FROM Papers p JOIN Citations c ON p.paper_id = c.citing_paper_id
            WHERE c.cited_paper_id = ?
        """, (paper_id,))
        paper['cited_by'] = rows_to_dicts(cursor.fetchall(), cursor)

        # Reviews
        cursor.execute("""
            SELECT r.review_id, r.rating, r.comment, u.name AS reviewer_name
            FROM Reviews r JOIN Users u ON r.user_id = u.user_id
            WHERE r.paper_id = ?
        """, (paper_id,))
        paper['reviews'] = rows_to_dicts(cursor.fetchall(), cursor)

        # Avg rating
        paper['avg_rating'] = round(
            sum(r['rating'] for r in paper['reviews']) / len(paper['reviews']), 1
        ) if paper['reviews'] else None

        # Include closest matched paper context for plagiarism transparency.
        cursor.execute(
            "SELECT paper_id, title, abstract FROM Papers WHERE paper_id != ? AND abstract IS NOT NULL",
            (paper_id,)
        )
        candidates = rows_to_dicts(cursor.fetchall(), cursor)
        best_match = find_best_match(paper_id, paper.get('abstract') or '', candidates)
        paper['matched_paper_id'] = best_match['paper_id'] if best_match else None
        paper['matched_paper_title'] = best_match['title'] if best_match else None
        paper['matched_similarity_score'] = best_match['similarity_score'] if best_match else 0.0

        # Log view activity
        cursor.execute(
            "INSERT INTO UserActivity (user_id, paper_id, activity_type) VALUES (?, ?, 'VIEW')",
            (user_id, paper_id)
        )
        cursor.execute(
            """UPDATE Paper_Statistics SET views = views + 1 WHERE paper_id = ?
               IF @@ROWCOUNT = 0 INSERT INTO Paper_Statistics (paper_id, views, downloads) VALUES (?, 1, 0)""",
            (paper_id, paper_id)
        )
        paper['views'] = (paper.get('views') or 0) + 1
        conn.commit()

        return jsonify(paper)
    finally:
        conn.close()


@papers_bp.route('/<int:paper_id>/download', methods=['POST'])
@jwt_required()
def download_paper(paper_id):
    """Log download activity and increment counter."""
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

        cursor.execute(
            "INSERT INTO UserActivity (user_id, paper_id, activity_type) VALUES (?, ?, 'DOWNLOAD')",
            (user_id, paper_id)
        )
        cursor.execute(
            """UPDATE Paper_Statistics SET downloads = downloads + 1 WHERE paper_id = ?
               IF @@ROWCOUNT = 0 INSERT INTO Paper_Statistics (paper_id, views, downloads) VALUES (?, 0, 1)""",
            (paper_id, paper_id)
        )
        conn.commit()
        return jsonify({'message': 'Download logged'})
    finally:
        conn.close()


@papers_bp.route('', methods=['POST'])
@jwt_required()
def upload_paper():
    """Upload a new paper. Researchers and Admins only."""
    claims = get_jwt()
    role_id = claims.get('role_id')
    if role_id not in [1, 2]:
        return jsonify({'error': 'Only Researchers and Admins can upload papers'}), 403

    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}

    def parse_unique_ints(values):
        parsed = []
        for value in values or []:
            try:
                int_value = int(value)
            except (TypeError, ValueError):
                continue
            if int_value not in parsed:
                parsed.append(int_value)
        return parsed

    title = data.get('title', '').strip()
    abstract = data.get('abstract', '').strip()
    publication_year = data.get('publication_year')
    author_ids = parse_unique_ints(data.get('author_ids', []))
    category_ids = parse_unique_ints(data.get('category_ids', []))
    new_author_name = data.get('new_author_name', '').strip()
    new_author_affiliation = data.get('new_author_affiliation', '').strip()
    new_category_name = data.get('new_category_name', '').strip()
    new_category_description = data.get('new_category_description', '').strip()

    if not title or not publication_year:
        return jsonify({'error': 'Title and publication year are required'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Insert paper
        cursor.execute(
            """INSERT INTO Papers (title, abstract, publication_year, uploaded_by)
               OUTPUT INSERTED.paper_id
               VALUES (?, ?, ?, ?)""",
            (title, abstract, publication_year, user_id)
        )
        paper_id = cursor.fetchone()[0]

        # Initialize statistics
        cursor.execute(
            "INSERT INTO Paper_Statistics (paper_id, views, downloads) VALUES (?, 0, 0)",
            (paper_id,)
        )

        # Handle new author
        if new_author_name:
            cursor.execute(
                """INSERT INTO Authors (author_name, affiliation)
                   OUTPUT INSERTED.author_id VALUES (?, ?)""",
                (new_author_name, new_author_affiliation)
            )
            new_id = cursor.fetchone()[0]
            author_ids.append(new_id)

        # Link authors
        for aid in author_ids:
            cursor.execute(
                "INSERT INTO Paper_Authors (paper_id, author_id) VALUES (?, ?)",
                (paper_id, aid)
            )

        # Link categories
        for cid in category_ids:
            cursor.execute(
                "INSERT INTO Paper_Categories (paper_id, category_id) VALUES (?, ?)",
                (paper_id, cid)
            )

        # Handle new category
        if new_category_name:
            cursor.execute(
                "SELECT TOP 1 category_id FROM Categories WHERE LOWER(category_name) = LOWER(?)",
                (new_category_name,)
            )
            category_row = cursor.fetchone()
            if category_row:
                new_category_id = category_row[0]
            else:
                cursor.execute(
                    """INSERT INTO Categories (category_name, description)
                       OUTPUT INSERTED.category_id VALUES (?, ?)""",
                    (new_category_name, new_category_description or None)
                )
                new_category_id = cursor.fetchone()[0]

            cursor.execute(
                "IF NOT EXISTS (SELECT 1 FROM Paper_Categories WHERE paper_id = ? AND category_id = ?) "
                "INSERT INTO Paper_Categories (paper_id, category_id) VALUES (?, ?)",
                (paper_id, new_category_id, paper_id, new_category_id)
            )

        # Log upload activity
        cursor.execute(
            "INSERT INTO UserActivity (user_id, paper_id, activity_type) VALUES (?, ?, 'UPLOAD')",
            (user_id, paper_id)
        )

        conn.commit()

        # Run plagiarism check after commit
        plag_result = check_plagiarism(paper_id, abstract)

        return jsonify({
            'message': 'Paper uploaded successfully',
            'paper_id': paper_id,
            'plagiarism': plag_result
        }), 201

    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@papers_bp.route('/<int:paper_id>', methods=['PUT'])
@jwt_required()
def update_paper(paper_id):
    """Update a paper. Admin can edit any; Researcher can edit own."""
    claims = get_jwt()
    role_id = claims.get('role_id')
    user_id = get_jwt_identity()

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT uploaded_by FROM Papers WHERE paper_id = ?", (paper_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Paper not found'}), 404
        if role_id != 1 and str(row[0]) != str(user_id):
            return jsonify({'error': 'Not authorized to edit this paper'}), 403

        data = request.get_json()
        cursor.execute(
            """UPDATE Papers SET title=?, abstract=?, publication_year=? WHERE paper_id=?""",
            (data.get('title'), data.get('abstract'), data.get('publication_year'), paper_id)
        )
        conn.commit()
        return jsonify({'message': 'Paper updated'})
    finally:
        conn.close()


@papers_bp.route('/<int:paper_id>', methods=['DELETE'])
@jwt_required()
def delete_paper(paper_id):
    """Delete a paper. Admin only."""
    claims = get_jwt()
    if claims.get('role_id') != 1:
        return jsonify({'error': 'Admin access required'}), 403

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Delete related records first
        for table in ['UserActivity', 'Bookmarks', 'Reviews', 'Paper_Statistics',
                      'PlagiarismReports', 'Paper_Authors', 'Paper_Categories']:
            cursor.execute(f"DELETE FROM {table} WHERE paper_id = ?", (paper_id,))
        cursor.execute("DELETE FROM Citations WHERE citing_paper_id=? OR cited_paper_id=?",
                       (paper_id, paper_id))
        cursor.execute("DELETE FROM Papers WHERE paper_id = ?", (paper_id,))
        conn.commit()
        return jsonify({'message': 'Paper deleted'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@papers_bp.route('/<int:paper_id>/review', methods=['POST'])
@jwt_required()
def add_review(paper_id):
    """Add a review/rating to a paper."""
    claims = get_jwt()
    role_id = claims.get('role_id')
    user_id = get_jwt_identity()
    data = request.get_json()
    rating = data.get('rating')
    comment = data.get('comment', '')

    if not rating or not (1 <= int(rating) <= 5):
        return jsonify({'error': 'Rating must be between 1 and 5'}), 400

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

        cursor.execute(
            "INSERT INTO Reviews (user_id, paper_id, rating, comment) VALUES (?, ?, ?, ?)",
            (user_id, paper_id, rating, comment)
        )
        conn.commit()
        return jsonify({'message': 'Review submitted'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@papers_bp.route('/authors', methods=['GET'])
@jwt_required()
def list_authors():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT author_id, author_name, affiliation FROM Authors ORDER BY author_name")
        return jsonify(rows_to_dicts(cursor.fetchall(), cursor))
    finally:
        conn.close()


@papers_bp.route('/categories', methods=['GET'])
@jwt_required()
def list_categories():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT category_id, category_name, description FROM Categories ORDER BY category_name")
        return jsonify(rows_to_dicts(cursor.fetchall(), cursor))
    finally:
        conn.close()
