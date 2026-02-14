---
permalink: /Mason2019VQRatio.html
layout: default
---

<div class="ref-controls">
  <a href="https://www.youtube.com/watch?v=GuKySqmxDd4&list=PLKbsytZxJw7_ObYvaAtmrzbFDUIzJvdU2&index=4&t=0s" target="_blank" class="ref-link">Link to Original Website</a>
  <a href="https://web.archive.org/web/https://www.youtube.com/watch?v=GuKySqmxDd4&list=PLKbsytZxJw7_ObYvaAtmrzbFDUIzJvdU2&index=4&t=0s" target="_blank" class="ref-link">Link to Page on Archive.org</a>
  <button onclick="loadArchive()" class="ref-button">View Archive Page in Frame</button>
</div>

<div class="ref-frame-container">
  <iframe id="ref-frame" src="https://www.youtube.com/watch?v=GuKySqmxDd4&list=PLKbsytZxJw7_ObYvaAtmrzbFDUIzJvdU2&index=4&t=0s"></iframe>
</div>

<script>
function loadArchive() {
  document.getElementById('ref-frame').src = 'https://web.archive.org/web/https://www.youtube.com/watch?v=GuKySqmxDd4&list=PLKbsytZxJw7_ObYvaAtmrzbFDUIzJvdU2&index=4&t=0s';
}
</script>
