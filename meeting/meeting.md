---
title: Meeting
layout: default
permalink: /meeting/
---

<div id="jaas-container" style="height: 700px; width: 100%;"></div>
<script src="https://8x8.vc/external_api.js"></script>
<script>
    const domain = "8x8.vc";
    const options = {
        roomName: "rykerrmedicalmeeting", // <-- match the room you used when generating JWT
        width: "100%",
        height: 700,
        parentNode: document.querySelector('#jaas-container'),
        jwt: "PASTE-YOUR-GENERATED-JWT-HERE"
    };

    const api = new JitsiMeetExternalAPI(domain, options);
</script>


