fetch("/assets/token.txt")
  .then(res => res.text())
  .then(jwt => {
    const options = {
      roomName: "mymeeting123",
      width: "100%",
      height: 700,
      parentNode: document.querySelector('#jaas-container'),
      jwt: jwt.trim()
    };
    const api = new JitsiMeetExternalAPI("8x8.vc", options);
  })
  .catch(err => console.error("❌ Could not load JWT:", err));

