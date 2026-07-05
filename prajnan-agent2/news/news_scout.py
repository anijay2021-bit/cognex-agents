import feedparser
import requests
from datetime import datetime
from loguru import logger
from config.settings import settings

class NewsScout:
    RSS_FEEDS = {
        "rbi": "https://rbi.org.in/rss/rss.aspx",
        "google_india_economy": "https://news.google.com/rss/search?q=india+economy+market&hl=en-IN&gl=IN",
        "google_rbi": "https://news.google.com/rss/search?q=RBI+india+monetary+policy&hl=en-IN&gl=IN",
        "google_nifty": "https://news.google.com/rss/search?q=nifty+banknifty+india&hl=en-IN&gl=IN",
        "google_crude": "https://news.google.com/rss/search?q=crude+oil+india+price&hl=en-IN&gl=IN",
        "google_politics": "https://news.google.com/rss/search?q=india+government+policy+economy&hl=en-IN&gl=IN",
        "moneycontrol": "https://www.moneycontrol.com/rss/marketreports.xml",
    }

    def __init__(self):
        self.finnhub_key = settings.finnhub_api_key
        self._last_seen = {}
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "Mozilla/5.0"})

    def scan_all_sources(self):
        all_news = []
        for source, url in self.RSS_FEEDS.items():
            items = self._fetch_rss(source, url)
            all_news.extend(items)
        if self.finnhub_key:
            all_news.extend(self._fetch_finnhub_news())
        seen = set()
        unique = []
        for item in all_news:
            key = item["headline"][:80]
            if key not in seen:
                seen.add(key)
                unique.append(item)
        unique.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        logger.info(f"News scan: {len(unique)} new items")
        return unique

    def _fetch_rss(self, source, url):
        items = []
        try:
            feed = feedparser.parse(url)
            last_seen = self._last_seen.get(source, "")
            for entry in feed.entries[:10]:
                title = entry.get("title", "")
                if title == last_seen:
                    break
                items.append({
                    "source": source,
                    "headline": title,
                    "summary": entry.get("summary", "")[:500],
                    "url": entry.get("link", ""),
                    "timestamp": entry.get("published", datetime.now().isoformat()),
                    "category": self._categorise(title),
                })
            if feed.entries:
                self._last_seen[source] = feed.entries[0].get("title", "")
        except Exception as e:
            logger.debug(f"RSS error ({source}): {e}")
        return items

    def _fetch_finnhub_news(self):
        items = []
        try:
            url = f"https://finnhub.io/api/v1/news?category=general&token={self.finnhub_key}"
            response = self._session.get(url, timeout=10)
            if response.status_code == 200:
                cutoff = datetime.now().timestamp() - 3600
                for item in response.json()[:15]:
                    if item.get("datetime", 0) > cutoff:
                        items.append({
                            "source": "FINNHUB",
                            "headline": item.get("headline", ""),
                            "summary": item.get("summary", "")[:400],
                            "url": item.get("url", ""),
                            "timestamp": datetime.fromtimestamp(item.get("datetime", 0)).isoformat(),
                            "category": self._categorise(item.get("headline", "")),
                        })
        except Exception as e:
            logger.debug(f"Finnhub error: {e}")
        return items

    def _categorise(self, text):
        text = text.lower()
        if any(w in text for w in ["rbi", "repo rate", "monetary policy", "inflation", "cpi"]):
            return "RBI_MONETARY"
        elif any(w in text for w in ["usfda", "fda", "pharma", "drug", "approval"]):
            return "PHARMA_FDA"
        elif any(w in text for w in ["budget", "government", "policy", "minister", "modi", "election", "vote"]):
            return "POLITICAL_POLICY"
        elif any(w in text for w in ["quarterly result", "earnings", "revenue beat", "profit", "eps beat", "eps miss"]):
            return "RESULTS"
        elif any(w in text for w in ["crude", "oil", "opec", "brent", "wti"]):
            return "CRUDE_OIL"
        elif any(w in text for w in ["usd", "rupee", "dollar", "forex", "currency", "fed", "federal reserve"]):
            return "CURRENCY_MACRO"
        elif any(w in text for w in ["sebi", "nse", "bse", "circuit", "ipo", "fii"]):
            return "MARKET_REGULATORY"
        elif any(w in text for w in ["result", "quarterly", "q1", "q2", "q3", "q4"]):
            return "RESULTS"
        else:
            return "GENERAL"

    def format_for_claude(self, news_items, max_items=20):
        if not news_items:
            return "No significant news in the last scan."
        lines = [f"=== NEWS SCAN ({datetime.now().strftime('%d-%b-%Y %H:%M IST')}) ===\n"]
        priority = ["RBI_MONETARY", "RESULTS", "CRUDE_OIL", "POLITICAL_POLICY", "PHARMA_FDA"]
        sorted_news = sorted(
            news_items[:max_items],
            key=lambda x: (0 if x.get("category") in priority else 1, x.get("timestamp", ""))
        )
        for i, item in enumerate(sorted_news[:max_items], 1):
            lines.append(f"{i}. [{item.get('category','GENERAL')}] [{item.get('source','')}] {item.get('headline','')}")
            if item.get("summary"):
                lines.append(f"   {item['summary'][:200]}")
        return "\n".join(lines)

news_scout = NewsScout()
