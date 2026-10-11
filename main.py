from scraper import fetch_reviews_as_dataframe
from analyzer import categorize_reviews
from rag_validator import run_rag_validation
from reporter import generate_jira_payload, generate_html_dashboard

def run_triage_pipeline():
    """Main orchestrator for the MoveInSync RAG Triage Pipeline."""
    print("=" * 55)
    print("   MoveInSync Play Store RAG Triage Pipeline")
    print("=" * 55)

    # STEP 1 — Scrape Play Store reviews
    print("\n[Step 1/4] Scraping Play Store reviews...")
    raw_df = fetch_reviews_as_dataframe('com.moveinsync.ets', count=1000)

    if raw_df.empty:
        print("Pipeline aborted: No data fetched.")
        return

    # STEP 2 — Keyword categorize (Engineering_Bug, Auth_Issue, etc.)
    print("\n[Step 2/4] Categorizing reviews by keyword tags...")
    total_df, negative_df = categorize_reviews(raw_df)

    # STEP 3 — RAG Validation + Deduplication
    print("\n[Step 3/4] Running RAG validation & semantic deduplication...")
    if not negative_df.empty:
        validated_df = run_rag_validation(negative_df)
    else:
        import pandas as pd
        validated_df = pd.DataFrame()
        print("[RAG] No negative reviews to validate.")

    # STEP 4 — Generate outputs
    print("\n[Step 4/4] Generating Jira tickets & HTML dashboard...")
    generate_jira_payload(validated_df)
    # Pass raw negative_df for accurate headline metrics (292, 29.2%) and
    # validated_df for the RAG cluster cards and Jira payload display.
    generate_html_dashboard(total_df, negative_df, validated_df)

    print("\n" + "=" * 55)
    print("   Pipeline Complete.")
    print("   → output/mock_jira_tickets.json")
    print("   → output/app_health_report.html")
    print("=" * 55)

if __name__ == "__main__":
    run_triage_pipeline()
