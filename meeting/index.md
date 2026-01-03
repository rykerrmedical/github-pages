---
title: Meeting
layout: default
permalink: /meeting/
---
<div id="password-form" style="max-width: 400px; margin: 50px auto; padding: 20px;">
  <h2>Enter Meeting Password</h2>
  <input type="password" id="meeting-password" placeholder="Password" style="width: 100%; padding: 10px; margin: 10px 0;">
  <button id="join-btn" style="width: 100%; padding: 10px; background: #4CAF50; color: white; border: none; cursor: pointer;">Join Meeting</button>
  <p id="error-msg" style="color: red; display: none;">Incorrect password</p>
</div>

<div id="jaas-container" style="height: 700px; width: 100%; display: none;"></div>
<script src="https://8x8.vc/external_api.js"></script>
<script src="/assets/jitsi.js"></script>
