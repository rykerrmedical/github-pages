---
title: Search
layout: default
permalink: /search/
---

<h1>Search</h1>

Beta testing for our new search feature! Give 'er a whirl and let us know what you think. She peruses an index of all the content we've made to pull content related to keywords. The system falls back to things we've referenced and a few trusted sources when we don't have anything specific in our content library. That said, she won't spit out a concise answer (i.e., she isn't an AI chat bot), rather she points you to the right place to look.

Pro tip: avoid terms like "site" or "guide" or "management" - they can obscure the search.

Still a work in progress, but we're getting there!

<div markdown="0">
<form id="search-form">
  <div class="search-input-wrap">
    <input
      type="text"
      id="search-input"
      name="q"
      placeholder="ask your question here!"
      autocomplete="off"
      role="combobox"
      aria-autocomplete="list"
      aria-expanded="false"
      aria-controls="search-suggest"
    />
    <ul id="search-suggest" role="listbox" aria-label="Suggested searches" hidden></ul>
  </div>
  <button type="submit">Search</button>
</form>

<label class="search-private">
  <input type="checkbox" id="search-private" />
  don't save my searches
  <span class="search-private-note">
  (we keep a tally of well-answered, common questions to suggest
  to other visitors; toggle this on and your searches will be omitted)
  </span>
</label>

<div id="search-status" role="status"></div>
<div id="search-results"></div>
</div>

<script>
(function () {
  var API_URL = "https://search.rykerrmedical.com/api/search";
  var SUGGEST_URL = "https://search.rykerrmedical.com/api/suggest";

  var form = document.getElementById('search-form');
  var input = document.getElementById('search-input');
  var status = document.getElementById('search-status');
  var results = document.getElementById('search-results');
  var suggestBox = document.getElementById('search-suggest');
  var privateBox = document.getElementById('search-private');

  // "Don't save my searches" -- remembered in this browser only.
  var PRIVATE_KEY = 'rykerr-search-private';
  function isPrivate() { return privateBox.checked; }
  try { privateBox.checked = localStorage.getItem(PRIVATE_KEY) === '1'; } catch (e) {}
  privateBox.addEventListener('change', function () {
    try { localStorage.setItem(PRIVATE_KEY, privateBox.checked ? '1' : '0'); } catch (e) {}
    if (privateBox.checked) hideSuggest();
  });

  // --- Suggested searches (past searches that pulled good results) ---
  var suggestItems = [];
  var suggestActive = -1;
  var suggestTimer = null;
  var suggestSeq = 0;

  function hideSuggest() {
    suggestBox.hidden = true;
    suggestBox.innerHTML = '';
    suggestItems = [];
    suggestActive = -1;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
  }

  function setActive(i) {
    suggestActive = i;
    Array.prototype.forEach.call(suggestBox.children, function (li, idx) {
      li.setAttribute('aria-selected', idx === i ? 'true' : 'false');
    });
    if (i >= 0) input.setAttribute('aria-activedescendant', 'search-suggest-' + i);
    else input.removeAttribute('aria-activedescendant');
  }

  function showSuggest(list) {
    suggestBox.innerHTML = '';
    suggestItems = list;
    suggestActive = -1;
    list.forEach(function (text, i) {
      var li = document.createElement('li');
      li.id = 'search-suggest-' + i;
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', 'false');
      li.textContent = text;
      // mousedown (not click) so it fires before the input's blur hides the list
      li.addEventListener('mousedown', function (e) {
        e.preventDefault();
        chooseSuggestion(text);
      });
      suggestBox.appendChild(li);
    });
    suggestBox.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  }

  function chooseSuggestion(text) {
    input.value = text;
    hideSuggest();
    runSearch(text);
  }

  function fetchSuggestions(q) {
    var seq = ++suggestSeq;
    fetch(SUGGEST_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ q: q })
    })
      .then(function (resp) { return resp.ok ? resp.json() : null; })
      .then(function (data) {
        // ignore stale replies (the visitor kept typing)
        if (seq !== suggestSeq || input.value.trim() !== q) return;
        if (data && data.suggestions && data.suggestions.length) showSuggest(data.suggestions);
        else hideSuggest();
      })
      .catch(function () { /* suggestions are a nicety; fail silently */ });
  }

  input.addEventListener('input', function () {
    clearTimeout(suggestTimer);
    var q = input.value.trim();
    if (q.length < 2 || isPrivate()) { suggestSeq++; hideSuggest(); return; }
    suggestTimer = setTimeout(function () { fetchSuggestions(q); }, 180);
  });

  input.addEventListener('keydown', function (e) {
    if (suggestBox.hidden || !suggestItems.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((suggestActive + 1) % suggestItems.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((suggestActive - 1 + suggestItems.length) % suggestItems.length);
    } else if (e.key === 'Enter' && suggestActive >= 0) {
      e.preventDefault();
      chooseSuggestion(suggestItems[suggestActive]);
    } else if (e.key === 'Escape') {
      hideSuggest();
    }
  });

  input.addEventListener('blur', function () { setTimeout(hideSuggest, 120); });

  var SITE_NAMES = {
    wikem: 'WikEM',
    deranged_physiology: 'Deranged Physiology',
    ibcc: 'IBCC',
    litfl: 'LITFL'
  };

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str == null ? '' : str;
    return div.innerHTML;
  }

  // The card's TYPE line — book / document / podcast / YouTube video /
  // website page / outside reference / external source (2026-09-26 card
  // redesign). 'book' vs 'document' comes from the tag the indexer set
  // automatically from which archive.org collection the PDF lives under
  // — see search-indexer/config.py's PDF_ARCHIVE_ITEM_CONTENT_TYPE.
  function contentTypeLabel(source) {
    if (source.source_type === 'external') {
      var tag = (source.tags && source.tags[0]) || '';
      return SITE_NAMES[tag] || 'External source';
    }
    if (source.source_type === 'pdf') {
      var pdfTag = (source.tags && source.tags[0]) || '';
      if (pdfTag === 'book') return 'Book by Rykerr Medical';
      if (pdfTag === 'document') return 'Document by Rykerr Medical';
      return 'Reference PDF';
    }
    if (source.source_type === 'citation') {
      return 'Outside reference';
    }
    if (source.source_type === 'audio') {
      return 'Audio recording by Rykerr Medical';
    }
    if (source.source_type === 'podcast' || source.source_type === 'podcast_transcript') {
      return 'Podcast';
    }
    if (source.source_type === 'youtube_transcript') {
      return 'YouTube video';
    }
    // Blog posts live at /YYYY/MM/DD/slug.html on the site.
    if (source.source_type === 'webpage' && source.locator_url) {
      try {
        if (/^\/\d{4}\/\d{2}\/\d{2}\//.test(new URL(source.locator_url).pathname)) return 'Blog post';
      } catch (e) {}
    }
    return 'Website page';
  }

  // Section/chapter to show next to the title. Comes straight off the
  // server for a PDF (its own `section` field — a page range's heading).
  // A webpage doesn't get a separate `section` from the server since
  // its own `locator` already IS the heading (see build_index.py's
  // index_webpages) — reuse that here instead of showing it twice.
  function sectionText(source) {
    if (source.section) return source.section;
    if (source.source_type === 'webpage' && source.locator) return source.locator;
    return '';
  }

  // The small locator line under the type (page number / timestamp /
  // citation note). Omitted for a webpage — its locator is already
  // shown as the section, not repeated below as well.
  function locatorText(source) {
    if (source.source_type === 'webpage') return '';
    return source.locator || '';
  }

  // Podcast/YouTube "see also" entries never carry a `section` (that's
  // a PDF chapter/heading concept) -- a plain locator like "39:12"
  // alone reads as a mystery timestamp, so label it by what it links
  // to instead. See retrieval._group_by_source (server) for why a
  // YouTube upload can show up here under its matching podcast episode.
  //
  // primarySourceType matters here: "YouTube version of the podcast"
  // is only a true statement when the PRIMARY card is itself a podcast
  // and this entry is its cross-referenced YouTube upload. When the
  // primary card is ALREADY a standalone YouTube video with no
  // matching podcast (nothing groups by title into an "episode" unless
  // BOTH exist), its own "see also" entries are just other good-
  // matching timestamps of that SAME video -- calling one of those
  // "the YouTube version of the podcast" is nonsense (there is no
  // podcast). Caught real, 2026-09-28, on "Stylets & Bougies for
  // Kiddos" (a video-only upload with no podcast counterpart).
  function relatedLabel(rel, primarySourceType) {
    if (rel.section && rel.locator) return rel.section + '; ' + rel.locator;
    if (rel.section) return rel.section;
    if (rel.source_type === 'youtube_transcript' && primarySourceType !== 'youtube_transcript') {
      return rel.locator ? ('YouTube version of the podcast; ' + rel.locator) : 'YouTube version of the podcast';
    }
    return rel.locator || 'See also';
  }

  function buildCard(source) {
    var card = document.createElement('div');
    card.className = 'search-result-card';

    var main = document.createElement('a');
    main.className = 'search-result-main';
    main.href = source.locator_url || '#';
    if (source.locator_url) {
      main.target = '_blank';
      main.rel = 'noopener noreferrer';
    }

    var section = sectionText(source);
    var locator = locatorText(source);

    main.innerHTML =
      '<div class="search-result-title">' + escapeHtml(source.source_title) + '</div>' +
      (section ? '<div class="search-result-section">' + escapeHtml(section) + '</div>' : '') +
      '<div class="search-result-type">' + escapeHtml(contentTypeLabel(source)) + '</div>' +
      (locator ? '<div class="search-result-locator">' + escapeHtml(locator) + '</div>' : '') +
      (source.snippet ? '<div class="search-result-snippet">' + escapeHtml(source.snippet) + '</div>' : '');
    card.appendChild(main);

    if (source.alt_link && source.alt_link.url) {
      var altLink = document.createElement('a');
      altLink.className = 'search-result-altlink';
      altLink.href = source.alt_link.url;
      altLink.target = '_blank';
      altLink.rel = 'noopener noreferrer';
      altLink.textContent = (source.alt_link.label || 'Listen on Archive.org') + ' \u2192';
      card.appendChild(altLink);
    }

    if (source.related && source.related.length) {
      var relatedEl = document.createElement('div');
      relatedEl.className = 'search-result-related';
      relatedEl.innerHTML = '<div class="search-result-related-label">See also</div><ul>' +
        source.related.map(function (rel) {
          return '<li><a href="' + escapeHtml(rel.locator_url || '#') + '" target="_blank" rel="noopener noreferrer">' +
            escapeHtml(relatedLabel(rel, source.source_type)) + '</a></li>';
        }).join('') +
        '</ul>';
      card.appendChild(relatedEl);
    }

    return card;
  }

  function renderResults(data) {
    results.innerHTML = '';

    if (data.answer) {
      var answerEl = document.createElement('p');
      answerEl.className = 'search-answer';
      answerEl.textContent = data.answer;
      results.appendChild(answerEl);
    }

    if (data.sources && data.sources.length) {
      data.sources.forEach(function (source) {
        results.appendChild(buildCard(source));
      });
    } else if (!data.answer) {
      status.textContent = "No results — try rephrasing your question.";
    }
  }

  function runSearch(query) {
    results.innerHTML = '';
    status.className = '';
    status.textContent = 'Searching…';

    fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: query, private: isPrivate() })
    })
      .then(function (resp) {
        if (!resp.ok) {
          throw new Error('Search service returned ' + resp.status);
        }
        return resp.json();
      })
      .then(function (data) {
        status.textContent = '';
        renderResults(data);
      })
      .catch(function (err) {
        status.className = 'search-status-error';
        status.textContent = 'Something went wrong reaching search — try again in a moment.';
        console.error('search-beta error:', err);
      });
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var q = input.value.trim();
    if (!q) return;
    suggestSeq++;
    hideSuggest();
    runSearch(q);
  });
})();
</script>
