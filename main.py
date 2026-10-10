from scraper import fetch_reviews_as_dataframe
from analyzer import categorize_reviews
from reporter import generate_jira_payload, generate_html_dashboard

def run_triage_pipeline():
    """Main orchestrator for the Play Store Triage Pipeline."""
    print("--- Starting MoveInSync Triage Pipeline ---")
    
    # 1. Scrape the raw data
    raw_df = fetch_reviews_as_dataframe('com.moveinsync.ets', count=1000)
    
    if raw_df.empty:
        print("Pipeline aborted: No data fetched.")
        return
        
    # 2. Analyze and categorize
    total_df, negative_df = categorize_reviews(raw_df)
    
    # 3. Generate Artifacts (JSON & HTML)
    generate_jira_payload(negative_df)
    generate_html_dashboard(total_df, negative_df)
    
    print("--- Pipeline Execution Complete ---")

if __name__ == "__main__":
    run_triage_pipeline()
