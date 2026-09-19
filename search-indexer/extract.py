"""
Pulls the title and main body text out of a raw HTML page, stripping nav
bars, footers, and other boilerplate.

Uses trafilatura, which is purpose-built for "give me the article, not the
chrome around it" and handles arbitrary site templates reasonably well
without per-site tuning.
"""
import trafilatura
from bs4 import BeautifulSoup


def extract_title(html, url):
    soup = BeautifulSoup(html, "lxml")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return url


def extract_page(html, url):
    """
    Returns {"title": str, "text": str} or None if the page has no
    meaningful extractable content (e.g. a redirect stub, an empty
    listing page).
    """
    text = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=True,
        favor_recall=True,
    )
    if not text or len(text.split()) < 20:
        return None

    title = extract_title(html, url)
    return {"title": title, "text": text}


if __name__ == "__main__":
    import sys
    import crawl

    url = sys.argv[1] if len(sys.argv) > 1 else "https://rykerrmedical.com"
    html = crawl.fetch_html(url)
    if html is None:
        print("failed to fetch")
    else:
        page = extract_page(html, url)
        if page is None:
            print("no meaningful content extracted")
        else:
            print("TITLE:", page["title"])
            print("---")
            print(page["text"][:1500])
