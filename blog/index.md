---
title: The Rykerr Medical Blog
layout: default
permalink: /blog/
---

# Rykerr Medical Blog

<!-- Tag filter (kept safe for Markdown with markdown="0") -->
<div markdown="0">
  <label for="tag-select">filter by tag:&nbsp;</label>
  <select id="tag-select">
    <option value="">all tags</option>
    {% assign all_tags = site.tags | sort %}
    {% for tag in all_tags %}
      <option value="{{ tag[0] }}">{{ tag[0] }}</option>
    {% endfor %}
  </select>
</div>

<ul id="posts-list">
  {% for post in site.posts %}
    <li data-tags="{{ post.tags   join: ',' }}">
      <article>
        <h3><a href="{{ post.url | relative_url }}">{{ post.title }}</a></h3>
        <p class="post-meta">{{ post.date | date: "%b %d, %Y" }}
          {% if post.tags.size > 0 %}
            &nbsp;&nbsp;|&nbsp;&nbsp;
            {% for tag in post.tags %}
              <span class="tag">{{ tag }}</span>
            {% endfor %}
          {% endif %}
        </p>
        <p class="post-blurb">{{ post.blurb }}</p>
      </article>
    </li>
  {% endfor %}
</ul>

<script>
(function () {
  const select = document.getElementById('tag-select');
  const items = Array.from(document.querySelectorAll('#posts-list > li'));

  function apply() {
    const tag = (select.value || '').toLowerCase();
    items.forEach(li => {
      if (!tag) { li.style.display = ''; return; }
      const tags = (li.getAttribute('data-tags') || '')
        .toLowerCase()
        .split(',')
        .map(s => s.trim());
      li.style.display = tags.includes(tag) ? '' : 'none';
    });
  }

  if (select) select.addEventListener('change', apply);
})();
</script>

