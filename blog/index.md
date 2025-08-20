---
title: The Rykerr Medical Blog
layout: default
permalink: /blog/
---

# Rykerr Medical Blog


Filter by tag:  
<select id="tag-select">
  <option value="">All Tags</option>
  {% assign all_tags = site.tags | sort %}
  {% for tag in all_tags %}
    <option value="{{ tag[0] }}">{{ tag[0] | capitalize }}</option>
  {% endfor %}
</select>

Search posts:  
<input type="text" id="search-input" placeholder="Search blog posts..." style="width: 300px;">

---

## Posts

<div id="posts-container">
{% for post in site.posts %}
- ### [{{ post.title }}]({{ post.url }})
  {{ post.excerpt | strip_html | truncatewords: 40 }}

  *Tags:* {% for tag in post.tags %}[{{ tag }}](/tags/{{ tag | slugify }}/){% unless forloop.last %}, {% endunless %}{% endfor %}
{% endfor %}
</div>

<script>
  const tagSelect = document.getElementById('tag-select');
  const searchInput = document.getElementById('search-input');
  const posts = document.querySelectorAll('#posts-container li, #posts-container article, #posts-container div');

  function filterPosts() {
    const selectedTag = tagSelect.value.toLowerCase();
    const searchTerm = searchInput.value.toLowerCase();

    posts.forEach(post => {
      const text = post.innerText.toLowerCase();
      const matchesTag = selectedTag === '' || text.includes(selectedTag);
      const matchesSearch = searchTerm === '' || text.includes(searchTerm);

      post.style.display = (matchesTag && matchesSearch) ? '' : 'none';
    });
  }

  tagSelect.addEventListener('change', filterPosts);
  searchInput.addEventListener('input', filterPosts);
</script>
