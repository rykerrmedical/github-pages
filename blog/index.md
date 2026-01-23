---
title: Rykerr Medical Blog
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
    <li data-tags='{{ post.tags | jsonify }}'>
      <article>
        <h3><a href="{{ post.url | relative_url }}">{{ post.title }}</a></h3>
        <p class="post-meta">{{ post.blurb }}; {{ post.date | date: "%b %d, %Y" }}</p>
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

        const raw = li.getAttribute('data-tags') || '[]';
        let tags = [];
        try {
            // data-tags is JSON (["Tag One","Tag, Two"])
            tags = JSON.parse(raw).map(s => (s || '').trim().toLowerCase());
        } catch (err) {
            // fallback (shouldn't be needed when using jsonify)
            tags = raw.split(',').map(s => (s || '').trim().toLowerCase());
        }

    li.style.display = tags.includes(tag) ? '' : 'none';
    });

  }

  if (select) {
  select.addEventListener('change', apply);
  // apply now so a preselected option or bookmarked filter is honored on load
  apply();
}
})();
</script>

also, if you're the nerdy type and want the blog's RSS feed for whatever RSS app or feed tool you use, it is [https://www.rykerrmedical.com/blog-feed.xml](https://www.rykerrmedical.com/blog-feed.xml)
