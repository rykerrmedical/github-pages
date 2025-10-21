document.addEventListener("DOMContentLoaded", () => {
  const roomName = "rykerrmedicalmeeting"; // you can make this dynamic if you want

  async function startMeeting(room) {
    try {
      const res = await fetch("/.netlify/functions/jitsi-token", {
        method: "POST",
        body: JSON.stringify({ room })
      });

      const { token } = await res.json();

      const domain = "8x8.vc"; // your Jitsi domain
      const options = {
        roomName: room,
        jwt: token,
        parentNode: document.getElementById("jaas-container"),
        width: "100%",
        height: 700
      };

      const api = new JitsiMeetExternalAPI(domain, options);

      api.addEventListener("videoConferenceJoined", () => {
        console.log("✅ Jitsi meeting joined successfully");
      });

      api.addEventListener("videoConferenceLeft", () => {
        console.log("🛑 Left the meeting");
      });

    } catch (err) {
      console.error("❌ Could not load JWT:", err);
    }
  }

  startMeeting(roomName);
});

