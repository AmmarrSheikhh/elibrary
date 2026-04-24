from flask import jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from flask import Blueprint
from utils.db import get_db_connection, rows_to_dicts

rec_bp = Blueprint('recommendations', __name__)


@rec_bp.route('', methods=['GET'])
@jwt_required()
def get_recommendations():
    """
    Recommendation algorithm:
    1. Find categories the user has interacted with (views, downloads, bookmarks)
    2. Find papers in those categories the user hasn't seen
    3. Also factor in highly-rated papers
    4. Return top 10 recommendations
    """
    user_id = get_jwt_identity()
    role_id = get_jwt().get('role_id')
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Get user's category preferences from activity + bookmarks
        cursor.execute("""
            SELECT pc.category_id, COUNT(*) AS weight
            FROM UserActivity ua
            JOIN Paper_Categories pc ON ua.paper_id = pc.paper_id
            WHERE ua.user_id = ?
            GROUP BY pc.category_id

            UNION ALL

            SELECT pc.category_id, 2 AS weight  -- bookmarks count double
            FROM Bookmarks b
            JOIN Paper_Categories pc ON b.paper_id = pc.paper_id
            WHERE b.user_id = ?
        """, (user_id, user_id))
        rows = cursor.fetchall()

        from collections import defaultdict
        category_weights = defaultdict(int)
        for row in rows:
            category_weights[row[0]] += row[1]

        if not category_weights:
            # Cold start: return most viewed papers
            visibility_clause = ""
            params = []
            if role_id != 1:
                visibility_clause = "WHERE COALESCE(pr.flagged, 0) = 0 OR p.uploaded_by = ?"
                params.append(user_id)

            cursor.execute("""
                SELECT TOP 10
                       p.paper_id,
                       p.title,
                       p.abstract,
                       p.publication_year,
                       COALESCE(ps.views, 0) AS views,
                       COALESCE(ps.downloads, 0) AS downloads,
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
                       'Popular' AS reason
                FROM Papers p
                LEFT JOIN Paper_Statistics ps ON p.paper_id = ps.paper_id
                LEFT JOIN PlagiarismReports pr ON p.paper_id = pr.paper_id
            """ + visibility_clause + """
                ORDER BY COALESCE(ps.views, 0) DESC, p.paper_id DESC
            """, params)
            return jsonify({
                'recommendations': rows_to_dicts(cursor.fetchall(), cursor),
                'type': 'popular'
            })

        # Build weighted recommendation
        # Papers in preferred categories, scored by category weight + paper popularity
        category_ids = list(category_weights.keys())
        placeholders = ','.join(['?' for _ in category_ids])
        weights_case = ' '.join([
            f"WHEN pc.category_id = {int(cid)} THEN {int(weight)}"
            for cid, weight in category_weights.items()
        ])

        visibility_clause = ""
        extra_params = []
        if role_id != 1:
            visibility_clause = "AND (COALESCE(pr.flagged, 0) = 0 OR p.uploaded_by = ?)"
            extra_params.append(user_id)

        cursor.execute(f"""
            SELECT TOP 10
                p.paper_id,
                p.title,
                p.abstract,
                p.publication_year,
                COALESCE(ps.views, 0) AS views,
                COALESCE(ps.downloads, 0) AS downloads,
                SUM(CASE {weights_case} ELSE 0 END) +
                    COALESCE(ps.views, 0) * 0.1 +
                    COALESCE(ps.downloads, 0) * 0.2 AS score,
                (
                    SELECT STRING_AGG(a.author_name, ', ')
                    FROM Paper_Authors pa
                    JOIN Authors a ON pa.author_id = a.author_id
                    WHERE pa.paper_id = p.paper_id
                ) AS authors,
                (
                    SELECT STRING_AGG(c.category_name, ', ')
                    FROM Paper_Categories pc2
                    JOIN Categories c ON pc2.category_id = c.category_id
                    WHERE pc2.paper_id = p.paper_id
                ) AS categories,
                'Based on your activity' AS reason
            FROM Papers p
            JOIN Paper_Categories pc ON p.paper_id = pc.paper_id
            LEFT JOIN Paper_Statistics ps ON p.paper_id = ps.paper_id
                        LEFT JOIN PlagiarismReports pr ON p.paper_id = pr.paper_id
            WHERE pc.category_id IN ({placeholders})
              AND p.paper_id NOT IN (
                  SELECT DISTINCT paper_id FROM UserActivity WHERE user_id = ? AND paper_id IS NOT NULL
              )
                            {visibility_clause}
            GROUP BY p.paper_id, p.title, p.abstract, p.publication_year, ps.views, ps.downloads
            ORDER BY score DESC
                """, category_ids + [user_id] + extra_params)

        recommendations = rows_to_dicts(cursor.fetchall(), cursor)

        # If fewer than 5 results, pad with popular papers
        if len(recommendations) < 5:
            seen_ids = [r['paper_id'] for r in recommendations]
            excluded = ','.join([str(i) for i in seen_ids]) if seen_ids else '0'

            trending_visibility_clause = ""
            trending_params = []
            if role_id != 1:
                trending_visibility_clause = "AND (COALESCE(pr.flagged, 0) = 0 OR p.uploaded_by = ?)"
                trending_params.append(user_id)

            cursor.execute(f"""
                SELECT TOP 5
                       p.paper_id,
                       p.title,
                       p.abstract,
                       p.publication_year,
                       COALESCE(ps.views, 0) AS views,
                       COALESCE(ps.downloads, 0) AS downloads,
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
                       'Trending' AS reason
                FROM Papers p
                LEFT JOIN Paper_Statistics ps ON p.paper_id = ps.paper_id
                LEFT JOIN PlagiarismReports pr ON p.paper_id = pr.paper_id
                WHERE p.paper_id NOT IN ({excluded})
                {trending_visibility_clause}
                ORDER BY COALESCE(ps.views, 0) DESC, p.paper_id DESC
            """, trending_params)
            recommendations += rows_to_dicts(cursor.fetchall(), cursor)

        return jsonify({'recommendations': recommendations, 'type': 'personalized'})

    except Exception:
        return jsonify({'error': 'Failed to generate recommendations'}), 500

    finally:
        conn.close()
