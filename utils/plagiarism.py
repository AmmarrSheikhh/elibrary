import re
from utils.db import get_db_connection, rows_to_dicts

PLAGIARISM_THRESHOLD = 20.0  # percent

STOPWORDS = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'has', 'he',
    'her', 'hers', 'him', 'his', 'i', 'if', 'in', 'into', 'is', 'it', 'its', 'me',
    'my', 'of', 'on', 'or', 'our', 'ours', 'she', 'that', 'the', 'their', 'theirs',
    'them', 'they', 'this', 'to', 'was', 'we', 'were', 'what', 'when', 'where',
    'which', 'who', 'why', 'will', 'with', 'you', 'your', 'yours', 'hi', 'hello',
    'im', 'am'
}

def tokenize(text):
    """Tokenize text into lowercase words."""
    if not text:
        return []
    words = re.findall(r"[a-z0-9']+", text.lower())
    return [w for w in words if len(w) >= 2 and w not in STOPWORDS]

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

    # Keyword overlap
    set1 = set(tokens1)
    set2 = set(tokens2)
    intersection = set1 & set2
    union = set1 | set2
    jaccard = len(intersection) / len(union) if union else 0
    containment = len(intersection) / min(len(set1), len(set2)) if set1 and set2 else 0

    # N-gram overlap
    bigrams1 = set(get_ngrams(tokens1, 2))
    bigrams2 = set(get_ngrams(tokens2, 2))
    bigram_intersection = bigrams1 & bigrams2
    bigram_union = bigrams1 | bigrams2
    bigram_sim = len(bigram_intersection) / len(bigram_union) if bigram_union else 0

    trigrams1 = set(get_ngrams(tokens1, 3))
    trigrams2 = set(get_ngrams(tokens2, 3))
    trigram_intersection = trigrams1 & trigrams2
    trigram_union = trigrams1 | trigrams2
    trigram_sim = len(trigram_intersection) / len(trigram_union) if trigram_union else 0

    # Penalize very short text comparisons to avoid inflated scores on tiny abstracts.
    min_len = min(len(tokens1), len(tokens2))
    min_unique = min(len(set1), len(set2))
    length_factor = min(1.0, min_len / 15.0)
    uniqueness_factor = min(1.0, min_unique / 8.0)

    base_similarity = (
        0.45 * containment +
        0.30 * jaccard +
        0.15 * bigram_sim +
        0.10 * trigram_sim
    )

    similarity = base_similarity * length_factor * uniqueness_factor * 100
    return round(similarity, 2)


def find_best_match(source_paper_id, source_abstract, candidate_papers):
    """Find the most similar paper to source abstract from candidate papers."""
    best_match = None
    best_score = 0.0

    for paper in candidate_papers:
        if paper.get('paper_id') == source_paper_id:
            continue

        score = compute_similarity(source_abstract, paper.get('abstract'))
        if score > best_score:
            best_score = score
            best_match = {
                'paper_id': paper.get('paper_id'),
                'title': paper.get('title'),
                'similarity_score': score,
            }

    return best_match

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
            """SELECT paper_id, title, abstract
               FROM Papers
               WHERE paper_id != ? AND abstract IS NOT NULL""",
            (new_paper_id,)
        )
        existing = rows_to_dicts(cursor.fetchall(), cursor)

        best_match = find_best_match(new_paper_id, new_abstract, existing)
        max_score = best_match['similarity_score'] if best_match else 0.0

        cited_ids = set()
        if best_match:
            cursor.execute(
                "SELECT cited_paper_id FROM Citations WHERE citing_paper_id = ?",
                (new_paper_id,)
            )
            cited_ids = {row[0] for row in cursor.fetchall()}

        citation_match = bool(best_match and best_match['paper_id'] in cited_ids)
        flagged = 1 if max_score >= PLAGIARISM_THRESHOLD and not citation_match else 0

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

        return {
            'similarity_score': max_score,
            'flagged': bool(flagged),
            'citation_match': citation_match,
            'matched_paper_id': best_match['paper_id'] if best_match else None,
            'matched_paper_title': best_match['title'] if best_match else None,
            'matched_similarity_score': best_match['similarity_score'] if best_match else 0.0,
        }

    finally:
        conn.close()
