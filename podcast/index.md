---
layout: default
title: Podcast
permalink: /podcast/
---

<h1>The Rykerr Medical Podcast</h1>
<div id="episode-list" style="max-width:800px; margin:2rem auto; text-align:left;">
  <p>Loading episodes…</p>
</div>

<script>
async function loadFeed() {
  const CORS_PROXY = "https://api.allorigins.win/raw?url=";
  const feedUrl = "https://rykerrmedical.github.io/landing/feed.xml";
  try {
    const resp = await fetch(CORS_PROXY + encodeURIComponent(feedUrl));
    if (!resp.ok) throw new Error("Failed to fetch feed");
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
      const audioUrl = enclosure ? enclosure.getAttribute("url") : null;
      const pubDate = item.querySelector("pubDate")?.textContent;
      const div = document.createElement("div");
      div.style.marginBottom = "2rem";
      div.innerHTML = `
        <h3 style="margin-bottom:0.3rem;">${title}</h3>
        ${pubDate ? `<small>${pubDate}</small>` : ""}
        ${audioUrl ? `<audio controls src="${audioUrl}" style="width:100%; margin-top:0.5rem;"></audio>` : ""}
        ${link ? `<p><a href="${link}" target="_blank">View episode details</a></p>` : ""}
      `;
      container.appendChild(div);
    });
  } catch (err) {
    document.getElementById("episode-list").textContent = "Error loading episodes.";
    console.error(err);
  }
}

document.addEventListener("DOMContentLoaded", loadFeed);
</script>
