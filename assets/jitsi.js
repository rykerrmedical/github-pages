document.addEventListener("DOMContentLoaded", () => {
    fetch("/.netlify/functions/jitsi-token", {
      method: "GET",
      body: JSON.stringify({ room: "rykerrmedicalmeeting" })
    })
      .then(res => res.json())
      .then(({ token }) => {
        // remove invalid characters or extra whitespace
        const cleanToken = token.replace(/(\r\n|\n|\r)/gm, "").trim();

        console.log("JWT token:", cleanToken);

        const options = {
          roomName: "vpaas-magic-cookie-e515f4dfdbe24ae3a34c4247de2675db/rykerrmedicalmeeting",
          parentNode: document.querySelector('#jaas-container'),
          width: "100%",
          height: 700,
          jwt: cleanToken
        };

        const domain = "8x8.vc";
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
