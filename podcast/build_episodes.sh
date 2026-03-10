#!/usr/bin/env bash
# build_episodes.sh
# Run during CI/CD (GitHub Actions) before Jekyll build.
# Fetches the podcast RSS feed and converts it to a static JSON file
# so the podcast page loads instantly without a CORS proxy.

set -euo pipefail

FEED_URL="https://rykerrmedical.github.io/landing/feed.xml"
OUTPUT_DIR="podcast"
OUTPUT_FILE="${OUTPUT_DIR}/episodes.json"

mkdir -p "$OUTPUT_DIR"

echo "Fetching feed from ${FEED_URL}..."
XML=$(curl -sS --fail --max-time 30 "$FEED_URL")

echo "Parsing feed to JSON..."
python3 -c "
import xml.etree.ElementTree as ET
import json, sys, html

xml_text = sys.stdin.read()
root = ET.fromstring(xml_text)
channel = root.find('channel')

ns = {
    'itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd',
    'media':  'http://search.yahoo.com/mrss/',
}

episodes = []
for item in channel.findall('item'):
    title = item.findtext('title', 'Untitled')
    link = item.findtext('link', '')
    pub_date = item.findtext('pubDate', '')

    enc = item.find('enclosure')
    audio_url = enc.get('url', '') if enc is not None else ''

    desc = item.findtext('description', '')

    image = None
    itunes_img = item.find('itunes:image', ns)
    if itunes_img is not None:
        image = itunes_img.get('href')
    else:
        media_c = item.find('media:content', ns)
        if media_c is not None:
            image = media_c.get('url')

    categories = [c.text.strip().lower() for c in item.findall('category') if c.text]

    apple_url = item.findtext('apple', '').strip() or None
    spotify_url = item.findtext('spotify', '').strip() or None

    episodes.append({
        'title': title,
        'link': link,
        'audioUrl': audio_url,
        'pubDate': pub_date,
        'description': desc,
        'image': image,
        'categories': categories,
        'applePodcastsUrl': apple_url,
        'spotifyUrl': spotify_url,
    })

print(json.dumps(episodes, indent=2))
" <<< "$XML" > "$OUTPUT_FILE"

echo "Wrote $(python3 -c "import json; print(len(json.load(open('${OUTPUT_FILE}'))))" ) episodes to ${OUTPUT_FILE}"
