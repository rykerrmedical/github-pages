---
permalink: /Strong2014.html
layout: default
---

<div class="ref-controls">
  <a href="https://www.youtube.com/playlist?list=PLFDCF820E88FC83ED" target="_blank" class="ref-link">Link to Original Website</a>
  <a href="https://web.archive.org/web/https://www.youtube.com/playlist?list=PLFDCF820E88FC83ED" target="_blank" class="ref-link">Link to Page on Archive.org</a>
  <a href="#" onclick="loadArchive(); return false;" class="ref-link">View Archive Page in Frame</a>
</div>

<div class="ref-frame-container">
  <iframe id="ref-frame" src="https://www.youtube.com/playlist?list=PLFDCF820E88FC83ED"></iframe>
</div>

<script>
function loadArchive() {
  document.getElementById('ref-frame').src = 'https://web.archive.org/web/https://www.youtube.com/playlist?list=PLFDCF820E88FC83ED';
}
</script>
