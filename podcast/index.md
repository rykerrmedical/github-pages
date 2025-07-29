---
title: Podcast
layout: default
permalink: /podcast/
---

<h1>The Rykerr Medical Podcast</h1>

<!-- External platform links -->
<div style="margin: 1rem 0; display: flex; gap: 1.5rem; flex-wrap: wrap;">
  <a href="https://podcasts.apple.com/us/podcast/the-rykerr-medical-podcast/id1570765323" target="_blank" style="text-decoration: none; color: #a31232; font-family: 'Black Ground', sans-serif; font-weight: bold; display: flex; align-items: center; gap: 0.4rem;">
    🎧 <span>Apple Podcasts</span>
  </a>
  <a href="https://open.spotify.com/show/73oflsb0c9M5iwHw07MxdP?" target="_blank" style="text-decoration: none; color: #a31232; font-family: 'Black Ground', sans-serif; font-weight: bold; display: flex; align-items: center; gap: 0.4rem;">
    🎧 <span>Spotify</span>
  </a>
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
      let image = null;
      const itunesImage = item.getElementsByTagName("itunes:image")[0];
      if (itunesImage) {
        image = itunesImage.getAttribute("href");
      }
      if (!image) {
        const mediaContent = item.getElementsByTagName("media:content")[0];
        image = mediaContent?.getAttribute("url") || null;
      }

      const div = document.createElement("div");
      
      if (image) {
        const imgEl = document.createElement("img");
        imgEl.src = image;
        imgEl.alt = title;
        imgEl.style.width = "250px";
        imgEl.style.height = "250px";
        imgEl.style.objectFit = "cover";
        imgEl.style.marginBottom = "1rem";
        imgEl.style.borderRadius = "12px";
        imgEl.style.boxShadow = "0 4px 12px rgba(0,0,0,0.1)";
        div.appendChild(imgEl);
      }

      const shortDescription = description && description.length > 400
        ? description.slice(0, 400) + "..."
        : description;

      if (shortDescription) {
        const pEl = document.createElement("p");
        pEl.textContent = shortDescription;
        pEl.style.fontSize = "0.95rem";
        pEl.style.lineHeight = "1.4";
        pEl.style.marginTop = "0.5rem";
        div.appendChild(pEl);
      }

      div.style.marginBottom = "3rem";

      if (i === 0) {
        // Latest episode
        div.innerHTML = `
          <h2>${title}</h2>
          <small>${pubDate}</small><br>
          ${image ? `<img src="${image}" alt="Episode image" style="max-width:100%; height:auto; margin-top:0.5rem; border-radius:8px;">` : ""}
          ${audioUrl ? `<audio controls src="${audioUrl}" style="width:100%; margin:1rem 0;"></audio>` : ""}
          ${shortDescription ? `<p>${shortDescription}</p>` : ""}
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
