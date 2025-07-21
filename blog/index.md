---
title: Blog
layout: default
---

# Blog

Stay updated with posts and reflections.

<ul>
  {% for post in site.posts %}
    <li><a href="{{ post.url }}">{{ post.title }}</a> — {{ post.date | date: "%b %d, %Y" }}</li>
  {% endfor %}
</ul>

