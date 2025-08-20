---
title: The Rykerr Medical Blog
layout: default
permalink: /blog/
---

# Rykerr Medical Blog


<label for="tag-select">Filter by tag:</label>
<select id="tag-select">
  <option value="">All Tags</option>
  {% assign all_tags = site.tags | sort %}
  {% for tag in all_tags %}
    <option value="{{ tag[0] }}">{{ tag[0] | capitalize }}</option>
  {% endfor %}
</select>

<label for="search-input" style="margin-left:1em;">Search posts:</label>
<input type="text" id="search-input" placeholder="Search blog posts..." style="width: 300px;">

<div id="posts-container" style="margin-top: 1em;">
  {% for post in site.posts %}
    <article class="post" data-tags="{{ post.tags | join: ' ' }}">
      <h2><a href="{{ post.url }}">{{ post.title }}</a></h2>
      <p>{{ post.excerpt | strip_html | truncatewords: 40 }}</p>
      <p><small>Tags: 
        {% for tag in post.tags %}
          <a href="/tags/{{ tag | slugify }}/">{{ tag }}</a>{% unless forloop.last %}, {% endunless %}
        {% endfor %}
      </small></p>
    </article>
  {% endfor %}
</div>

<script>
  const tagSelect = document.getElementById('tag-select');
  const searchInput = document.getElementById('search-input');
  const posts = document.querySelectorAll('#posts-container .post');

  function filterPosts() {
    const selectedTag = tagSelect.value.toLowerCase();
    const searchTerm = searchInput.value.toLowerCase();

    posts.forEach(post => {
      const tags = post.getAttribute('data-tags').toLowerCase();
      const title = post.querySelector('h2').innerText.toLowerCase();
      const excerpt = post.querySelector('p').innerText.toLowerCase();

      const matchesTag = selectedTag === '' || tags.includes(selectedTag);
      const matchesSearch = searchTerm === '' || title.includes(searchTerm) || excerpt.includes(searchTerm);

      if (matchesTag && matchesSearch) {
        post.style.display = '';
      } else {
        post.style.display = 'none';
      }
    });
  }

  tagSelect.addEventListener('change', filterPosts);
  searchInput.addEventListener('input', filterPosts);
</script>
