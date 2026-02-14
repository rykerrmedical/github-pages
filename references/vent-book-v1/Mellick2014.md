---
permalink: /Mellick2014.html
layout: default
---

<div class="ref-controls">
  <a href="https://www.youtube.com/watch?v=ERnJY9p-BfY" target="_blank" class="ref-link">Link to Original Website</a>
  <a href="https://web.archive.org/web/https://www.youtube.com/watch?v=ERnJY9p-BfY" target="_blank" class="ref-link">Link to Page on Archive.org</a>
  <button onclick="loadArchive()" class="ref-button">View Archive Page in Frame</button>
</div>

<div class="ref-frame-container">
  <iframe id="ref-frame" src="https://www.youtube.com/watch?v=ERnJY9p-BfY"></iframe>
</div>

<script>
function loadArchive() {
  document.getElementById('ref-frame').src = 'https://web.archive.org/web/https://www.youtube.com/watch?v=ERnJY9p-BfY';
}
</script>
