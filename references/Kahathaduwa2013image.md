---
layout: default
title: Reference - Kahathaduwa2013image
permalink: /Kahathaduwa2013image.html
original_url: https://owlcation.com/stem/Lung-Pressures-and-Lung-Compliance
archive_url: https://web.archive.org/web/https://owlcation.com/stem/Lung-Pressures-and-Lung-Compliance
---

<div class="reference-page">
  <h1>Reference: Kahathaduwa2013image</h1>
  
  <div class="reference-options">
    <div class="option-card">
      <h2>📄 View Original Source</h2>
      <p>Access the reference at its original location</p>
      <a href="https://owlcation.com/stem/Lung-Pressures-and-Lung-Compliance" target="_blank" class="btn btn-primary">Open Original</a>
      <a href="#embed-original" class="btn btn-secondary" onclick="loadEmbed('original')">View in Frame</a>
    </div>
    
    <div class="option-card">
      <h2>📚 View on Archive.org</h2>
      <p>Access a preserved copy on the Internet Archive</p>
      <a href="https://web.archive.org/web/https://owlcation.com/stem/Lung-Pressures-and-Lung-Compliance" target="_blank" class="btn btn-primary">Open Archive</a>
      <a href="#embed-archive" class="btn btn-secondary" onclick="loadEmbed('archive')">View in Frame</a>
    </div>
  </div>
  
  <div id="embed-container" class="embed-container" style="display: none;">
    <div class="embed-header">
      <button onclick="closeEmbed()" class="btn-close">✕ Close</button>
      <a id="embed-external" href="" target="_blank" class="btn btn-link">Open in New Tab →</a>
    </div>
    <iframe id="reference-iframe" src="" frameborder="0"></iframe>
  </div>
</div>

<style>
.reference-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 2rem;
}

.reference-options {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 2rem;
  margin: 2rem 0;
}

.option-card {
  border: 1px solid #ddd;
  border-radius: 8px;
  padding: 2rem;
  text-align: center;
  background: #f9f9f9;
}

.option-card h2 {
  margin-top: 0;
  color: #333;
}

.btn {
  display: inline-block;
  padding: 0.75rem 1.5rem;
  margin: 0.5rem;
  border-radius: 4px;
  text-decoration: none;
  font-weight: 500;
  transition: all 0.2s;
}

.btn-primary {
  background: #007bff;
  color: white;
  border: none;
}

.btn-primary:hover {
  background: #0056b3;
}

.btn-secondary {
  background: #6c757d;
  color: white;
  border: none;
}

.btn-secondary:hover {
  background: #545b62;
}

.btn-link {
  color: #007bff;
}

.embed-container {
  margin-top: 2rem;
  border: 1px solid #ddd;
  border-radius: 8px;
  overflow: hidden;
}

.embed-header {
  background: #f1f1f1;
  padding: 1rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.btn-close {
  background: #dc3545;
  color: white;
  border: none;
  padding: 0.5rem 1rem;
  border-radius: 4px;
  cursor: pointer;
}

.btn-close:hover {
  background: #c82333;
}

#reference-iframe {
  width: 100%;
  height: 800px;
  border: none;
}
</style>

<script>
function loadEmbed(type) {
  const embedContainer = document.getElementById('embed-container');
  const iframe = document.getElementById('reference-iframe');
  const externalLink = document.getElementById('embed-external');
  
  let url;
  if (type === 'original') {
    url = 'https://owlcation.com/stem/Lung-Pressures-and-Lung-Compliance';
  } else {
    url = 'https://web.archive.org/web/https://owlcation.com/stem/Lung-Pressures-and-Lung-Compliance';
  }
  
  iframe.src = url;
  externalLink.href = url;
  embedContainer.style.display = 'block';
  
  // Scroll to iframe
  embedContainer.scrollIntoView({ behavior: 'smooth' });
}

function closeEmbed() {
  const embedContainer = document.getElementById('embed-container');
  const iframe = document.getElementById('reference-iframe');
  
  embedContainer.style.display = 'none';
  iframe.src = '';
}
</script>
