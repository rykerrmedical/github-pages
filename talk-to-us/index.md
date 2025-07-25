---
layout: default
title: Talk to Us
permalink: /talk-to-us/
---

<h1>Talk to Us</h1>

<p>Send us a question or share your thoughts</p>

<form
  id="contact-form"
  action="https://formspree.io/f/mvgqakzo"
  method="POST"
  style="max-width: 600px; margin: 2rem auto;"
>
  <label for="name">Name (optional)</label><br>
  <input type="text" id="name" name="name" style="width: 100%; padding: 0.5rem;"><br><br>

  <label for="email">Email (optional, but needed for a reply)</label><br>
  <input type="email" id="email" name="_replyto" style="width: 100%; padding: 0.5rem;"><br><br>

  <label for="category">Category (Clinical, Tech, CEUs...)</label><br>
  <input type="text" id="category" name="category" style="width: 100%; padding: 0.5rem;"><br><br>

  <label for="message">What's the question or thought?</label><br>
  <textarea id="message" name="message" required rows="5" style="width: 100%; padding: 0.5rem;"></textarea><br><br>

  <button type="submit" style="padding: 0.5rem 1rem; font-weight: bold;">send it!</button>
</form>

<div id="thank-you" style="display: none; text-align: center; margin-top: 2rem;">
  <h2>Thanks a bunch!</h2>
  <p>We’ll get back to you as soon as we can.</p>
</div>

<script>
  const form = document.getElementById('contact-form');
  const thankYou = document.getElementById('thank-you');

  form.addEventListener('submit', async function(event) {
    event.preventDefault();

    const formData = new FormData(form);
    const action = form.getAttribute('action');

    try {
      const response = await fetch(action, {
        method: 'POST',
        body: formData,
        headers: {
          'Accept': 'application/json'
        }
      });

      if (response.ok) {
        form.style.display = 'none';
        thankYou.style.display = 'block';
      } else {
        alert('Something went wrong. Please try again later.');
      }
    } catch (error) {
      alert('Error submitting form. Please try again.');
    }
  });
</script>
