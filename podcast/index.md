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


<div id="latest-episode" style="max-width: 800px; margin: 2rem auto;"></div>
<div id="episode-grid" class="episode-grid"></div>


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

    const latestContainer = document.getElementById("latest-episode");
    const gridContainer = document.getElementById("episode-grid");

    items.forEach((item, i) => {
      const title = item.querySelector("title")?.textContent || "Untitled";
      const link = item.querySelector("link")?.textContent;
      const enclosure = item.querySelector("enclosure");
      const audioUrl = enclosure?.getAttribute("url");
      const pubDateRaw = item.querySelector("pubDate")?.textContent;
      const pubDate = pubDateRaw ? new Date(pubDateRaw).toDateString() : "";
      const description = item.querySelector("description")?.textContent || "";

      let image = null;
      const itunesImage = item.getElementsByTagName("itunes:image")[0];
      if (itunesImage) {
        image = itunesImage.getAttribute("href");
      } else {
        const mediaContent = item.getElementsByTagName("media:content")[0];
        image = mediaContent?.getAttribute("url") || null;
      }

      const div = document.createElement("div");

      if (i === 0) {
        // === Featured episode layout ===
        div.innerHTML = `
          <h2>${title}</h2>
          <small>${pubDate}</small><br>
          ${image ? `<img src="${image}" alt="${title}" style="width:100%; max-width:320px; height:auto; border-radius:12px; margin:1rem 0;" loading="lazy">` : ""}
          ${audioUrl ? `<audio controls src="${audioUrl}" style="width:100%; margin-bottom:1rem;"></audio>` : ""}
          <p style="line-height:1.5;">${description.length > 400 ? description.slice(0, 400) + '...' : description}</p>
          ${description.length > 400 ? `<button style="background:none;border:none;color:#a31232;cursor:pointer;" onclick="this.previousElementSibling.textContent='${description.replace(/'/g, "\\'")}'; this.remove();">Read More</button>` : ""}
          <hr style="margin-top: 2rem;">
        `;
        latestContainer.appendChild(div);
      } else {
        // === Older episode cards ===
        div.classList.add("episode-card");

        if (image) {
          const img = document.createElement("img");
          img.src = image;
          img.alt = title;
          img.loading = "lazy";
          div.appendChild(img);
        }

        const titleEl = document.createElement("h4");
        titleEl.textContent = title;
        div.appendChild(titleEl);

        const dateEl = document.createElement("small");
        dateEl.textContent = pubDate;
        div.appendChild(dateEl);

        if (audioUrl) {
          const audio = document.createElement("audio");
          audio.controls = true;
          audio.src = audioUrl;
          div.appendChild(audio);
        }

        if (description) {
          const short = description.length > 300 ? description.slice(0, 300) + "..." : description;
          const descP = document.createElement("p");
          descP.textContent = short;
          div.appendChild(descP);

          if (description.length > 300) {
            const btn = document.createElement("button");
            btn.textContent = "Read More";
            btn.style.background = "none";
            btn.style.border = "none";
            btn.style.color = "#a31232";
            btn.style.cursor = "pointer";
            btn.onclick = () => {
              descP.textContent = description;
              btn.remove();
            };
            div.appendChild(btn);
          }
        }

        gridContainer.appendChild(div);
      }
    });
  } catch (err) {
    document.getElementById("episode-list").textContent = "Error loading episodes.";
    console.error(err);
  }
}

document.addEventListener("DOMContentLoaded", loadFeed);
</script>

