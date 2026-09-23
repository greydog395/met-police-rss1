from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup


CONFIG_FILE = "config.yml"
OUTPUT_DIRECTORY = Path("public")
OUTPUT_FILE = OUTPUT_DIRECTORY / "feed.xml"

USER_AGENT = (
    "Mozilla/5.0 (compatible; ObsidianRSSFeed/1.0; "
    "+https://github.com/)"
)


def clean_text(value: str | None) -> str:
    """Remove HTML and normalize whitespace."""
    if not value:
        return ""

    value = html.unescape(str(value))
    value = re.sub(
        r"<script.*?</script>",
        "",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    value = re.sub(
        r"<style.*?</style>",
        "",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def escape_xml(value: str | None) -> str:
    """Escape text for use in XML."""
    return html.escape(str(value or ""), quote=True)


def parse_date(text: str) -> datetime:
    """
    Extract dates such as:

    22 September 2026 16:30
    4 September 2026 12:19
    """

    match = re.search(
        r"\b(\d{1,2})\s+"
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+"
        r"(\d{4})"
        r"(?:\s+(\d{1,2}):(\d{2}))?",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return datetime.now(timezone.utc)

    day = int(match.group(1))
    month_name = match.group(2)
    year = int(match.group(3))
    hour = int(match.group(4) or 0)
    minute = int(match.group(5) or 0)

    month = datetime.strptime(month_name[:3], "%b").month

    return datetime(
        year,
        month,
        day,
        hour,
        minute,
        tzinfo=timezone.utc,
    )


def scrape_met_police_page(source: dict) -> list[dict]:
    """Scrape article links from the Met Police tag page."""
    source_name = source["name"]
    source_url = source["url"]

    print(f"Downloading: {source_url}")

    response = requests.get(
        source_url,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Focus on the main page content.
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.body
        or soup
    )

    items = []
    seen_links = set()

    for link_element in main.find_all("a", href=True):
        href = link_element.get("href", "").strip()
        title = clean_text(link_element.get_text(" ", strip=True))

        if not href or not title:
            continue

        article_url = urljoin(source_url, href)

        # Only include links from the Met Police news website.
        if not article_url.startswith("https://news.met.police.uk/"):
            continue

        # Ignore navigation and non-article pages.
        ignored_paths = [
            "/tag/",
            "/category/",
            "/search",
            "/contact",
            "/about",
            "/privacy",
            "/terms",
        ]

        if any(path in article_url.lower() for path in ignored_paths):
            continue

        # Ignore very short links, which are usually navigation items.
        if len(title) < 10:
            continue

        if article_url in seen_links:
            continue

        seen_links.add(article_url)

        # Find the surrounding article/list item text.
        container = (
            link_element.find_parent("article")
            or link_element.find_parent("li")
            or link_element.parent
        )

        if container:
            container_text = clean_text(
                container.get_text(" ", strip=True)
            )
        else:
            container_text = title

        # Ignore obvious navigation/footer content.
        unwanted_text = [
            "follow",
            "subscribe",
            "contact us",
            "privacy policy",
            "terms of use",
            "accept cookies",
        ]

        if any(
            phrase in container_text.lower()
            for phrase in unwanted_text
        ):
            continue

        published_at = parse_date(container_text)

        description = container_text

        # Remove the title from the description.
        description = description.replace(title, "", 1)

        # Remove dates from the description.
        description = re.sub(
            r"\b\d{1,2}\s+"
            r"(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+"
            r"\d{4}"
            r"(?:\s+\d{1,2}:\d{2})?",
            "",
            description,
            flags=re.IGNORECASE,
        )

        description = clean_text(description)

        if not description:
            description = (
                f"New Met Police article: {title}"
            )

        items.append(
            {
                "id": article_url,
                "title": title,
                "link": article_url,
                "description": description,
                "published_at": published_at,
                "source_name": source_name,
                "source_url": source_url,
            }
        )

    print(f"Found {len(items)} possible articles")

    return items


def build_rss(config: dict, items: list[dict]) -> str:
    """Generate an RSS 2.0 XML document."""
    title = config.get("title", "Combined RSS Feed")
    description = config.get("description", "")
    website_url = config.get("website_url", "")
    feed_url = config.get("feed_url", "")

    generated_at = datetime.now(timezone.utc)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0"',
        '     xmlns:atom="http://www.w3.org/2005/Atom">',
        "  <channel>",
        f"    <title>{escape_xml(title)}</title>",
        f"    <description>{escape_xml(description)}</description>",
        f"    <link>{escape_xml(website_url)}</link>",
        (
            f'    <atom:link href="{escape_xml(feed_url)}" '
            'rel="self" type="application/rss+xml" />'
        ),
        "    <language>en-gb</language>",
        (
            f"    <lastBuildDate>"
            f"{format_datetime(generated_at)}"
            f"</lastBuildDate>"
        ),
        "    <generator>GitHub Actions RSS Generator</generator>",
    ]

    for item in items:
        lines.extend(
            [
                "    <item>",
                f"      <title>{escape_xml(item['title'])}</title>",
                f"      <link>{escape_xml(item['link'])}</link>",
                (
                    '      <guid isPermaLink="true">'
                    f"{escape_xml(item['id'])}"
                    "</guid>"
                ),
                (
                    f"      <pubDate>"
                    f"{format_datetime(item['published_at'])}"
                    f"</pubDate>"
                ),
                (
                    f"      <description>"
                    f"{escape_xml(item['description'])}"
                    f"</description>"
                ),
                (
                    f'      <source url="'
                    f"{escape_xml(item['source_url'])}">"
                    f"{escape_xml(item['source_name'])}"
                    "</source>"
                ),
                "    </item>",
            ]
        )

    lines.extend(
        [
            "  </channel>",
            "</rss>",
            "",
        ]
    )

    return "\n".join(lines)


def main() -> None:
    with open(CONFIG_FILE, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    all_items = []

    for source in config.get("sources", []):
        try:
            items = scrape_met_police_page(source)
            all_items.extend(items)
        except Exception as error:
            print(
                f"Error scraping {source.get('url')}: {error}"
            )

    # Remove duplicate articles using their URLs.
    unique_items = {}

    for item in all_items:
        unique_items[item["id"]] = item

    items = list(unique_items.values())

    # Newest articles first.
    items.sort(
        key=lambda item: item["published_at"],
        reverse=True,
    )

    max_items = int(config.get("max_items", 50))
    items = items[:max_items]

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    rss_xml = build_rss(config, items)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        file.write(rss_xml)

    print(f"Generated: {OUTPUT_FILE}")
    print(f"Included {len(items)} articles")


if __name__ == "__main__":
    main()
