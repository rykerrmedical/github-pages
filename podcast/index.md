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
      
      // Get the raw HTML from CDATA - use firstChild.nodeValue for CDATA content
      const descNode = item.querySelector("description");
      let rawDesc = "";
      if (descNode && descNode.firstChild) {
        rawDesc = descNode.firstChild.nodeValue || descNode.textContent || "";
      }
      
      // Parse the HTML string to make links clickable
      const tempDiv = document.createElement("div");
      tempDiv.innerHTML = rawDesc;
      
      // Make sure links open in new tab
      tempDiv.querySelectorAll('a').forEach(a => {
        a.setAttribute('target', '_blank');
        a.setAttribute('rel', 'noopener noreferrer');
      });
      
      const description = tempDiv.innerHTML;

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
          ${image ? `<img src="${image}" alt="${title}" style="display:block; margin:1rem auto; width:100%; max-width:320px; height:auto; border-radius:12px;" loading="lazy">` : ""}
          ${audioUrl ? `<audio controls src="${audioUrl}" style="width:100%; margin-bottom:1rem;"></audio>` : ""}
          <div style="line-height:1.5;">${description.length > 400 ? description.slice(0, 400) + '...' : description}</div>
          ${description.length > 400 ? `<button class="read-more" data-full="${encodeURIComponent(description)}" style="background: none; border: none; color: #a31232; cursor: pointer;">read more</button>` : ""}
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
          const descDiv = document.createElement("div");
          descDiv.innerHTML = description;
          
          // Make links clickable after adding to DOM
          descDiv.querySelectorAll('a').forEach(a => {
            a.setAttribute('target', '_blank');
            a.setAttribute('rel', 'noopener noreferrer');
          });
          
          div.appendChild(descDiv);

          if (description.length > 300) {
            const btn = document.createElement("button");
            btn.textContent = "read more";
            btn.style.background = "none";
            btn.style.border = "none";
            btn.style.color = "#a31232";
            btn.style.cursor = "pointer";
            btn.style.display = "block";
            btn.style.marginTop = "0.5rem";
            btn.onclick = () => {
              descDiv.style.maxHeight = "none";
              descDiv.style.overflow = "visible";
              btn.remove();
            };
            div.appendChild(btn);
            
            // Truncate visually with CSS instead of slicing HTML
            descDiv.style.maxHeight = "6em";
            descDiv.style.overflow = "hidden";
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
