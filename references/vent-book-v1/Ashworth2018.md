---
permalink: /Ashworth2018.html
layout: default
---

<div class="ref-controls">
  <a href="https://www.sciencedirect.com/science/article/pii/S0883944117306986?via%3Dihub" target="_blank" class="ref-link">Link to Original Website</a>
  <a href="https://web.archive.org/web/https://www.sciencedirect.com/science/article/pii/S0883944117306986?via%253Dihub" target="_blank" class="ref-link">Link to Page on Archive.org</a>
  <button onclick="loadArchive()" class="ref-button">View Archive Page in Frame</button>
</div>

<div class="ref-frame-container">
  <iframe id="ref-frame" src="https://www.sciencedirect.com/science/article/pii/S0883944117306986?via%3Dihub"></iframe>
</div>

<script>
function loadArchive() {
  document.getElementById('ref-frame').src = 'https://web.archive.org/web/https://www.sciencedirect.com/science/article/pii/S0883944117306986?via%253Dihub';
}
</script>
