fetch("https://jitsi-for-rykerr-medical.netlify.app/.netlify/functions/jitsi-token?room=rykerrmedicalmeeting")
  .then(res => res.json())
  .then(({ token }) => {
    const cleanToken = token.replace(/(\r\n|\n|\r)/gm, "").trim();

    const options = {
      roomName: "vpaas-magic-cookie-e515f4dfdbe24ae3a34c4247de2675db/rykerrmedicalmeeting",
      parentNode: document.querySelector('#jaas-container'),
      width: "100%",
      height: 700,
      jwt: cleanToken,
      configOverwrite: {
        startWithAudioMuted: true,
        startWithVideoMuted: false,
        prejoinPageEnabled: true,
        fileRecordingsEnabled: true,
        enableWelcomePage: false,
        enableLobbyChat: true,
        hideLobbyButton: false
      }
    };

    const domain = "8x8.vc";
    const api = new JitsiMeetExternalAPI(domain, options);
  })
  .catch(err => console.error("❌ Could not load JWT:", err));
