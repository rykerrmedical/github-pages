---
permalink: /Cooper2019.html
layout: default
---

<div class="ref-controls">
  <a href="https://www.ncbi.nlm.nih.gov/books/NBK430743/" target="_blank" class="ref-link">Link to Original Website</a>
  <a href="https://web.archive.org/web/https://www.ncbi.nlm.nih.gov/books/NBK430743/" target="_blank" class="ref-link">Link to Page on Archive.org</a>
  <button onclick="loadArchive()" class="ref-button">View Archive Page in Frame</button>
</div>

<div class="ref-frame-container">
  <iframe id="ref-frame" src="https://www.ncbi.nlm.nih.gov/books/NBK430743/"></iframe>
</div>

<script>
function loadArchive() {
  document.getElementById('ref-frame').src = 'https://web.archive.org/web/https://www.ncbi.nlm.nih.gov/books/NBK430743/';
}
</script>
