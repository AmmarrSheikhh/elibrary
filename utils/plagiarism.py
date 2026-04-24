import re
from collections import Counter
from utils.db import get_db_connection, rows_to_dicts

PLAGIARISM_THRESHOLD = 20.0  # percent

def tokenize(text):
    """Tokenize text into lowercase words."""
    if not text:
        return []
    return re.findall(r'\b[a-z]{3,}\b', text.lower())

def get_ngrams(tokens, n=3):
    """Generate n-grams from token list."""
    return [tuple(tokens[i:i+n]) for i in range(len(tokens) - n + 1)]

def compute_similarity(text1, text2):
    """
    Compute similarity between two texts using combined keyword overlap + bigram matching.
    Returns a percentage (0-100).
    """
    tokens1 = tokenize(text1)
    tokens2 = tokenize(text2)

    if not tokens1 or not tokens2:
        return 0.0

    # Keyword overlap (Jaccard similarity)
    set1 = set(tokens1)
    set2 = set(tokens2)
    intersection = set1 & set2
    union = set1 | set2
    jaccard = len(intersection) / len(union) if union else 0

    # Bigram overlap
    bigrams1 = set(get_ngrams(tokens1, 2))
    bigrams2 = set(get_ngrams(tokens2, 2))
    bigram_intersection = bigrams1 & bigrams2
    bigram_union = bigrams1 | bigrams2
    bigram_sim = len(bigram_intersection) / len(bigram_union) if bigram_union else 0

    # Weighted combination
    similarity = (0.4 * jaccard + 0.6 * bigram_sim) * 100
    return round(similarity, 2)

def check_plagiarism(new_paper_id, new_abstract):
    """
    Compare new paper against all existing papers.
    Logs result to PlagiarismReports. Returns the max similarity score.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Get all existing papers except the new one
        cursor.execute(
            "SELECT paper_id, abstract FROM Papers WHERE paper_id != ? AND abstract IS NOT NULL",
            (new_paper_id,)
        )
        existing = rows_to_dicts(cursor.fetchall(), cursor)

        max_score = 0.0
        for paper in existing:
            score = compute_similarity(new_abstract, paper['abstract'])
            if score > max_score:
                max_score = score

        flagged = 1 if max_score >= PLAGIARISM_THRESHOLD else 0

        # Insert or update plagiarism report
        cursor.execute(
            """
            MERGE PlagiarismReports AS target
            USING (SELECT ? AS paper_id) AS source ON target.paper_id = source.paper_id
            WHEN MATCHED THEN
                UPDATE SET similarity_score = ?, flagged = ?
            WHEN NOT MATCHED THEN
                INSERT (paper_id, similarity_score, flagged) VALUES (?, ?, ?);
            """,
            (new_paper_id, max_score, flagged, new_paper_id, max_score, flagged)
        )
        conn.commit()

        return {'similarity_score': max_score, 'flagged': bool(flagged)}

    finally:
        conn.close()
