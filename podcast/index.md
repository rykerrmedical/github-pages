---
title: Rykerr Medical Podcast
layout: default
permalink: /podcast/
---

<h1>Rykerr Medical Podcast</h1>

<!-- Tag filter -->
<div markdown="0">
  <label for="tag-select">filter by tag:&nbsp;</label>
  <select id="tag-select">
    <option value="">all tags</option>
  </select>
</div>

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
<div id="episode-grid" class="episode-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 1rem;"></div>

<script>
async function loadFeed() {
  const CORS_PROXY = "https://api.allorigins.win/raw?url=";
  const feedUrl = "https://rykerrmedical.github.io/landing/feed.xml";

  try {
    const resp = await fetch(CORS_PROXY + encodeURIComponent(feedUrl));
    const xmlText = await resp.text();
    const parser = new DOMParser();
    const xml = parser.parseFromString(xmlText, "application/xml");
    const items = Array.from(xml.querySelectorAll("item"));

    const latestContainer = document.getElementById("latest-episode");
    const gridContainer = document.getElementById("episode-grid");
    const tagSelect = document.getElementById("tag-select");

    // --- collect all tags for dropdown ---
    let allTagsSet = new Set();

    const episodes = items.map((item, i) => {
      const title = item.querySelector("title")?.textContent || "Untitled";
      const link = item.querySelector("link")?.textContent;
      const enclosure = item.querySelector("enclosure");
      const audioUrl = enclosure?.getAttribute("url");
      const pubDateRaw = item.querySelector("pubDate")?.textContent;
      const pubDate = pubDateRaw ? new Date(pubDateRaw).toDateString() : "";

      const rawDesc = item.querySelector("description")?.textContent || "";
      function sanitizeHtml(input) {
        const tmp = document.createElement("div");
        tmp.innerHTML = input;
        tmp.querySelectorAll('a').forEach(a => {
          a.setAttribute('target', '_blank');
          a.setAttribute('rel', 'noopener noreferrer');
        });
        return tmp.innerHTML;
      }
      const description = sanitizeHtml(rawDesc);

      let image = null;
      const itunesImage = item.getElementsByTagName("itunes:image")[0];
      if (itunesImage) image = itunesImage.getAttribute("href");
      else {
        const mediaContent = item.getElementsByTagName("media:content")[0];
        image = mediaContent?.getAttribute("url") || null;
      }

      const categories = Array.from(item.querySelectorAll("category"))
                              .map(c => c.textContent.trim().toLowerCase());
      categories.forEach(tag => allTagsSet.add(tag));

      return { title, link, audioUrl, pubDate, description, image, categories, index: i };
    });

    // --- populate dropdown ---
    Array.from(allTagsSet).sort().forEach(tag => {
      const opt = document.createElement("option");
      opt.value = tag;
      opt.textContent = tag;
      tagSelect.appendChild(opt);
    });

    // --- render function ---
    function renderEpisodes(filterTag = "") {
      latestContainer.innerHTML = "";
      gridContainer.innerHTML = "";

      episodes.forEach(ep => {
        if (filterTag && !ep.categories.includes(filterTag)) return;

        const div = document.createElement("div");
        div.classList.add("episode-card");
        div.style.border = "1px solid #ccc";
        div.style.borderRadius = "8px";
        div.style.padding = "0.5rem";
        div.style.background = "#fff";
        div.style.display = "flex";
        div.style.flexDirection = "column";
        div.style.gap = "0.5rem";
        
        // Create a URL-friendly ID from the title
        const episodeId = ep.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
        div.id = episodeId;

        if (ep.image) {
          const img = document.createElement("img");
          img.src = ep.image;
          img.alt = ep.title;
          img.loading = "lazy";
          img.style.width = "100%";
          img.style.height = "auto";
          img.style.borderRadius = "6px";
          div.appendChild(img);
        }

        const titleEl = document.createElement("h4");
        titleEl.textContent = ep.title;
        titleEl.style.margin = "0";
        div.appendChild(titleEl);

        const dateEl = document.createElement("small");
        dateEl.textContent = ep.pubDate;
        div.appendChild(dateEl);

        if (ep.audioUrl) {
          const audio = document.createElement("audio");
          audio.controls = true;
          audio.src = ep.audioUrl;
          audio.style.width = "100%";
          div.appendChild(audio);
        }

        // Create button container
        const buttonContainer = document.createElement("div");
        buttonContainer.style.display = "flex";
        buttonContainer.style.gap = "0.5rem";
        buttonContainer.style.flexWrap = "wrap";
        buttonContainer.style.marginTop = "0.5rem";

        // Share this episode button
        const shareBtn = document.createElement("button");
        shareBtn.textContent = "share";
        shareBtn.classList.add("episode-button");
        shareBtn.style.background = "none";
        shareBtn.style.color = "#747373";
        shareBtn.style.border = "1px solid #747373";
        shareBtn.style.padding = "0.4rem 0.8rem";
        shareBtn.style.fontSize = "0.85rem";
        shareBtn.style.borderRadius = "6px";
        shareBtn.style.cursor = "pointer";
        shareBtn.style.boxShadow = "0 0 6px rgba(163, 18, 50, 0.3)";
        shareBtn.onclick = () => {
            const url = `${window.location.origin}${window.location.pathname}#${episodeId}`;
            navigator.clipboard.writeText(url).then(() => {
                shareBtn.textContent = "link copied!";
                setTimeout(() => shareBtn.textContent = "share", 2000);
            });
        };
        buttonContainer.appendChild(shareBtn);

        // Listen on Apple Podcasts button
        if (ep.link) {
            const appleBtn = document.createElement("a");
            appleBtn.href = "https://podcasts.apple.com/us/podcast/the-rykerr-medical-podcast/id1570765323";
            appleBtn.target = "_blank";
            appleBtn.rel = "noopener noreferrer";
            appleBtn.textContent = "apple podcasts";
            appleBtn.classList.add("episode-button");
            appleBtn.style.background = "none";
            appleBtn.style.color = "#747373";
            appleBtn.style.border = "1px solid #747373";
            appleBtn.style.padding = "0.4rem 0.8rem";
            appleBtn.style.fontSize = "0.85rem";
            appleBtn.style.borderRadius = "6px";
            appleBtn.style.textDecoration = "none";
            appleBtn.style.display = "inline-block";
            appleBtn.style.cursor = "pointer";
            appleBtn.style.boxShadow = "0 0 6px rgba(163, 18, 50, 0.3)";
            buttonContainer.appendChild(appleBtn);
        }

        // Listen on Spotify button
        const spotifyBtn = document.createElement("a");
        spotifyBtn.href = "https://open.spotify.com/show/73oflsb0c9M5iwHw07MxdP";
        spotifyBtn.target = "_blank";
        spotifyBtn.rel = "noopener noreferrer";
        spotifyBtn.textContent = "spotify";
        spotifyBtn.classList.add("episode-button");
        spotifyBtn.style.background = "none";
        spotifyBtn.style.color = "#747373";
        spotifyBtn.style.border = "1px solid #747373";
        spotifyBtn.style.padding = "0.4rem 0.8rem";
        spotifyBtn.style.fontSize = "0.85rem";
        spotifyBtn.style.borderRadius = "6px";
        spotifyBtn.style.textDecoration = "none";
        spotifyBtn.style.display = "inline-block";
        spotifyBtn.style.cursor = "pointer";
        spotifyBtn.style.boxShadow = "0 0 6px rgba(163, 18, 50, 0.3)";
        buttonContainer.appendChild(spotifyBtn);

        div.appendChild(buttonContainer);

        if (ep.description) {
          const short = ep.description.length > 200 ? ep.description.slice(0, 200) + "..." : ep.description;
          const descDiv = document.createElement("div");
          descDiv.innerHTML = short;
          div.appendChild(descDiv);

          if (ep.description.length > 200) {
            const btn = document.createElement("button");
            btn.textContent = "read more...";
            btn.style.background = "none";
            btn.style.border = "none";
            btn.style.color = "#a31232";
            btn.style.cursor = "pointer";
            btn.onclick = () => {
              descDiv.innerHTML = ep.description;
              btn.remove();
            };
            div.appendChild(btn);
          }
        }

        // featured episode only if no filter and first episode
        if (ep.index === 0 && !filterTag) latestContainer.appendChild(div);
        else gridContainer.appendChild(div);
      });
    }

    // --- initial render ---
    renderEpisodes();

    // --- filter on dropdown change ---
    tagSelect.addEventListener("change", () => {
      renderEpisodes(tagSelect.value.toLowerCase());
    });

  } catch (err) {
    gridContainer.textContent = "Error loading episodes.";
    console.error(err);
  }
}

document.addEventListener("DOMContentLoaded", loadFeed);

document.addEventListener("click", function (e) {
  if (e.target.matches(".read-more")) {
    const btn = e.target;
    const fullText = decodeURIComponent(btn.getAttribute("data-full"));
    const container = btn.previousElementSibling;
    if (container) container.innerHTML = fullText;
    btn.remove();
  }
});
</script>
