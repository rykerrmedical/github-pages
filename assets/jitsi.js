document.getElementById('join-btn').addEventListener('click', function() {
  const password = document.getElementById('meeting-password').value;
  
  fetch(`https://github-pages-kappa-rust.vercel.app/api/jitsi-token?room=rykerrmedicalmeeting&password=${encodeURIComponent(password)}`)
    .then(res => {
        console.log("Response status:", res.status);
        if (!res.ok) {
          throw new Error(`HTTP error! status: ${res.status}`);
        }
        return res.json();
    })
    .then(data => {
        console.log("Token received:", data.token ? "YES" : "NO");
        const { token } = data;
      // Hide password form, show meeting
      document.getElementById('password-form').style.display = 'none';
      document.getElementById('jaas-container').style.display = 'block';
      
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
    .catch(err => {
      console.error("❌ Could not load JWT:", err);
      document.getElementById('error-msg').style.display = 'block';
    });
});
