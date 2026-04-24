import uuid

from app import create_app
from flask_jwt_extended import create_access_token
from utils.db import get_db_connection
from utils.plagiarism import compute_similarity


def register_user(client, name, role_id):
    email = f"{name.lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}@example.com"
    payload = {
        "name": name,
        "email": email,
        "password": "123456",
        "role_id": role_id,
        "institution_id": 1,
    }
    resp = client.post("/api/auth/register", json=payload)
    data = resp.get_json() or {}
    return {
        "status": resp.status_code,
        "email": email,
        "token": data.get("token"),
        "user": data.get("user") or {},
    }


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def main():
    app = create_app()
    client = app.test_client()

    print("similarity_short_text", compute_similarity("hi im ammar", "hello im ammar"))

    # Register test users
    researcher = register_user(client, "Req Researcher", 2)
    student = register_user(client, "Req Student", 3)
    print("register_statuses", researcher["status"], student["status"])

    # Get an existing abstract to reliably trigger plagiarism against real paper
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT TOP 1 abstract FROM Papers WHERE abstract IS NOT NULL AND LEN(abstract) > 50 ORDER BY paper_id")
    row = cur.fetchone()
    existing_abstract = row[0] if row else "Neural sequence modeling and language representations with attention mechanisms."
    conn.close()

    new_category_name = f"ReqCategory_{uuid.uuid4().hex[:6]}"

    upload_payload = {
        "title": f"Req Upload {uuid.uuid4().hex[:6]}",
        "abstract": existing_abstract,
        "publication_year": 2026,
        "author_ids": [],
        "category_ids": [],
        "new_author_name": "Req Author",
        "new_author_affiliation": "Req Lab",
        "new_category_name": new_category_name,
        "new_category_description": "category from request validation",
    }
    upload_resp = client.post("/api/papers", json=upload_payload, headers=bearer(researcher["token"]))
    upload_data = upload_resp.get_json() or {}
    plag = upload_data.get("plagiarism") or {}
    uploaded_paper_id = upload_data.get("paper_id")
    print("upload_status", upload_resp.status_code)
    print("upload_plag_keys", {
        "flagged": plag.get("flagged"),
        "similarity_score": plag.get("similarity_score"),
        "matched_paper_id": plag.get("matched_paper_id"),
        "matched_paper_title": bool(plag.get("matched_paper_title")),
    })

    # Validate new category creation + linkage
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT TOP 1 category_id FROM Categories WHERE category_name = ?", (new_category_name,))
    cat_row = cur.fetchone()
    created_category_id = cat_row[0] if cat_row else None
    linked = 0
    if created_category_id and uploaded_paper_id:
        cur.execute(
            "SELECT COUNT(*) FROM Paper_Categories WHERE paper_id = ? AND category_id = ?",
            (uploaded_paper_id, created_category_id),
        )
        linked = cur.fetchone()[0]
    conn.close()
    print("category_created_and_linked", bool(created_category_id), linked)

    # Visibility test for flagged paper (hidden from other users)
    student_papers_resp = client.get("/api/papers?page=1&per_page=100", headers=bearer(student["token"]))
    student_papers_data = student_papers_resp.get_json() or {}
    student_paper_ids = {p.get("paper_id") for p in (student_papers_data.get("papers") or [])}
    print("student_papers_status", student_papers_resp.status_code)
    print("flagged_hidden_from_student", uploaded_paper_id not in student_paper_ids)

    if uploaded_paper_id:
        student_detail_resp = client.get(f"/api/papers/{uploaded_paper_id}", headers=bearer(student["token"]))
        researcher_detail_resp = client.get(f"/api/papers/{uploaded_paper_id}", headers=bearer(researcher["token"]))
        print("detail_visibility_statuses", student_detail_resp.status_code, researcher_detail_resp.status_code)

    # Top papers endpoint for non-admin
    top_resp = client.get("/api/papers/top?limit=5", headers=bearer(student["token"]))
    top_data = top_resp.get_json() or []
    print("top_papers_non_admin", top_resp.status_code, len(top_data))

    # Activity includes upload
    activity_resp = client.get("/api/users/activity", headers=bearer(researcher["token"]))
    activity = activity_resp.get_json() or []
    upload_activity_found = any(a.get("activity_type") == "UPLOAD" and a.get("paper_id") == uploaded_paper_id for a in activity)
    print("upload_activity_found", upload_activity_found)

    # Bookmark activity for student
    bookmark_target_id = None
    for p in (student_papers_data.get("papers") or []):
        pid = p.get("paper_id")
        if pid and pid != uploaded_paper_id:
            bookmark_target_id = pid
            break

    if bookmark_target_id:
        bookmark_resp = client.post(f"/api/users/bookmarks/{bookmark_target_id}", headers=bearer(student["token"]))
        student_activity_resp = client.get("/api/users/activity", headers=bearer(student["token"]))
        student_activity = student_activity_resp.get_json() or []
        bookmark_found = any(a.get("activity_type") == "BOOKMARK" and a.get("paper_id") == bookmark_target_id for a in student_activity)
        print("bookmark_status_and_activity", bookmark_resp.status_code, bookmark_found)
    else:
        print("bookmark_status_and_activity", "skipped_no_visible_paper")

    # Keyword search should work with author/category names too
    search_target_id = bookmark_target_id
    if search_target_id:
        detail_resp = client.get(f"/api/papers/{search_target_id}", headers=bearer(student["token"]))
        detail = detail_resp.get_json() or {}
        authors = detail.get("authors") or []
        categories = detail.get("categories") or []

        author_term = (authors[0].get("author_name") if authors else "")
        category_term = (categories[0].get("category_name") if categories else "")

        if author_term:
            author_search = client.get(f"/api/papers?keyword={author_term}", headers=bearer(student["token"]))
            author_hits = {p.get("paper_id") for p in ((author_search.get_json() or {}).get("papers") or [])}
            print("keyword_author_search_hit", search_target_id in author_hits)
        else:
            print("keyword_author_search_hit", "skipped_no_author")

        if category_term:
            cat_search = client.get(f"/api/papers?keyword={category_term}", headers=bearer(student["token"]))
            cat_hits = {p.get("paper_id") for p in ((cat_search.get_json() or {}).get("papers") or [])}
            print("keyword_category_search_hit", search_target_id in cat_hits)
        else:
            print("keyword_category_search_hit", "skipped_no_category")

    # Admin plagiarism report should include matched paper metadata
    with app.app_context():
        admin_token = create_access_token(
            identity="1",
            additional_claims={"role_id": 1, "name": "Ammar Arif", "email": "ammar@example.com"},
        )
    admin_resp = client.get("/api/admin/plagiarism?flagged=true", headers=bearer(admin_token))
    reports = admin_resp.get_json() or []
    report_has_match_fields = any(
        ("matched_paper_id" in r and "matched_paper_title" in r and "matched_similarity_score" in r)
        for r in reports
    )
    print("admin_report_match_fields", admin_resp.status_code, report_has_match_fields, len(reports))


if __name__ == "__main__":
    main()
