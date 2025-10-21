document.addEventListener("DOMContentLoaded", () => {
  const roomName = "rykerrmedicalmeeting"; // or make this dynamic

  async function startMeeting(room) {
    try {
      const res = await fetch("/.netlify/functions/jitsi-token", {
        method: "POST",
        body: JSON.stringify({ room })
      });

      const data = await res.json();

      if (!data.token) {
        throw new Error("No JWT returned from function");
      }

      const domain = "8x8.vc";
      const roomName = "vpaas-magic-cookie-e515f4dfdbe24ae3a34c4247de2675db/rykerrmedicalmeeting";
      const options = {
        roomName: room,
        jwt: data.token,
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
      console.error("❌ Could not load JWT or start meeting:", err);
    }
  }

  startMeeting(roomName);
});

