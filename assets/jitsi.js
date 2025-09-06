document.addEventListener("DOMContentLoaded", () => {
  fetch("/assets/token.txt?ts=" + Date.now()) // cache-buster
    .then(res => res.text())
    .then(jwt => {
      const options = {
        roomName: "mymeeting123",      // must match JWT.room
        width: "100%",
        height: 700,
        parentNode: document.querySelector('#jaas-container'),
        jwt: jwt.trim()
      };

      // Explicitly set the domain
        const domain = "8x8.vc/vpaas-magic-cookie-e515f4dfdbe24ae3a34c4247de2675db";

      const api = new JitsiMeetExternalAPI(domain, options);

      api.addEventListener("videoConferenceJoined", () => {
        console.log("✅ Jitsi meeting joined successfully");
      });

      api.addEventListener("videoConferenceLeft", () => {
        console.log("🛑 Left the meeting");
      });
    })
    .catch(err => console.error("❌ Could not load JWT:", err));
});
