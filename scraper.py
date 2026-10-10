from google_play_scraper import Sort, reviews
import pandas as pd

def fetch_reviews_as_dataframe(app_id='com.moveinsync.ets', count=1000, lang='en', country='in'):
    """Fetches reviews from the Play Store and returns a Pandas DataFrame."""
    print(f"Fetching up to {count} recent reviews for {app_id}...")
    try:
        result, _ = reviews(
            app_id,
            lang=lang,
            country=country,
            sort=Sort.NEWEST,
            count=count
        )
        print(f"Successfully fetched {len(result)} reviews.")
        if not result:
            return pd.DataFrame()
        return pd.DataFrame(result)
    except Exception as e:
        print(f"Failed to fetch for {app_id}: {e}")
        return pd.DataFrame()
