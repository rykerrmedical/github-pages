---
layout: default
title: Podcast
permalink: /podcast/
---

<h1>The Rykerr Medical Podcast</h1>

<!-- External platform links -->
<div style="margin: 1rem 0; display: flex; gap: 1rem; flex-wrap: wrap;">
  <a href="https://podcasts.apple.com/us/podcast/the-rykerr-medical-podcast/id1570765323" target="_blank" style="color: #a31232; font-weight: bold;">🎧 Listen on Apple Podcasts</a>
  <a href="https://open.spotify.com/show/73oflsb0c9M5iHw07MxdP?" target="_blank" style="color: #1DB954; font-weight: bold;">🎧 Listen on Spotify</a>
</div>

<div id="episode-list" style="max-width:800px; margin:2rem auto; text-align:left;">
  <p>Loading episodes…</p>
</div>

<script>
async function loadFeed() {
  const CORS_PROXY = "https://api.allorigins.win/raw?url=";
  const feedUrl = "https://rykerrmedical.github.io/landing/feed.xml";

  try {
    const resp = await fetch(CORS_PROXY + encodeURIComponent(feedUrl));
    const xmlText = await resp.text();
    const parser = new DOMParser();
    const xml = parser.parseFromString(xmlText, "application/xml");
    const items = xml.querySelectorAll("item");
    const container = document.getElementById("episode-list");
    container.innerHTML = "";

    items.forEach((item, i) => {
      const title = item.querySelector("title")?.textContent || "Untitled";
      const link = item.querySelector("link")?.textContent;
      const enclosure = item.querySelector("enclosure");
      const audioUrl = enclosure?.getAttribute("url");
      const pubDateRaw = item.querySelector("pubDate")?.textContent;
      const pubDate = pubDateRaw ? new Date(pubDateRaw).toDateString() : "";
      const description = item.querySelector("description")?.textContent;
      const image = item.querySelector("itunes\\:image")?.getAttribute("href") ||
                    item.querySelector("media\\:content")?.getAttribute("url");

      const div = document.createElement("div");
      div.style.marginBottom = "3rem";

      // Recent episode with image & description
      if (i === 0) {
        div.innerHTML = `
          <h2>${title}</h2>
          <small>${pubDate}</small><br>
          ${image ? `<img src="${image}" alt="Episode image" style="max-width:100%; height:auto; margin-top:0.5rem; border-radius:8px;">` : ""}
          ${audioUrl ? `<audio controls src="${audioUrl}" style="width:100%; margin:1rem 0;"></audio>` : ""}
          ${description ? `<p>${description}</p>` : ""}
          ${link ? `<p><a href="${link}" target="_blank">Full episode details</a></p>` : ""}
          <hr style="margin-top: 2rem;">
        `;
      } else {
        // Older episodes
        div.innerHTML = `
          <h3>${title}</h3>
          <small>${pubDate}</small><br>
          ${audioUrl ? `<audio controls src="${audioUrl}" style="width:100%; margin-top:0.5rem;"></audio>` : ""}
          ${link ? `<p><a href="${link}" target="_blank">Details</a></p>` : ""}
        `;
      }

      container.appendChild(div);
    });
  } catch (err) {
    document.getElementById("episode-list").textContent = "Error loading episodes.";
    console.error(err);
  }
}

document.addEventListener("DOMContentLoaded", loadFeed);
</script>

