---
title: Meeting
layout: default
permalink: /meeting/
---

<div id="jaas-container" style="height: 700px; width: 100%;"></div>
<script src="https://8x8.vc/external_api.js"></script>
<script>
  const domain = "8x8.vc";
  const roomName = "mymeeting123"; // fixed or dynamic

  fetch("/token.txt")  // file updated by your script
    .then(res => res.text())
    .then(jwt => {
      const options = {
        roomName,
        width: "100%",
        height: 700,
        parentNode: document.querySelector('#jaas-container'),
        jwt: jwt.trim()
      };
      const api = new JitsiMeetExternalAPI(domain, options);
    })
    .catch(err => console.error("❌ Could not load JWT:", err));
</script>


