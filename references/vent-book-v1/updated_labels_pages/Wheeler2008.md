---
permalink: /Wheeler2008.html
layout: default
---

<div class="ref-controls">
  <a href="https://books.google.com/books?id=1o1iUQUCSwgC&printsec=frontcover&source=gbs_ge_summary_r&cad=0#v=onepage&q&f=false" target="_blank" class="ref-link">Link to Original Website</a>
  <a href="https://web.archive.org/web/https://books.google.com/books?id=1o1iUQUCSwgC&printsec=frontcover&source=gbs_ge_summary_r&cad=0#v=onepage&q&f=false" target="_blank" class="ref-link">Link to Page on Archive.org</a>
  <button onclick="loadArchive()" class="ref-button">View Archive Page in Frame</button>
</div>

<div class="ref-frame-container">
  <iframe id="ref-frame" src="https://books.google.com/books?id=1o1iUQUCSwgC&printsec=frontcover&source=gbs_ge_summary_r&cad=0#v=onepage&q&f=false"></iframe>
</div>

<script>
function loadArchive() {
  document.getElementById('ref-frame').src = 'https://web.archive.org/web/https://books.google.com/books?id=1o1iUQUCSwgC&printsec=frontcover&source=gbs_ge_summary_r&cad=0#v=onepage&q&f=false';
}
</script>
