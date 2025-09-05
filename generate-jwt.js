const fs = require("fs");
const jwt = require("jsonwebtoken");
const { execSync } = require("child_process");

// Load your private key
const privateKey = fs.readFileSync("private.key", "utf8");

// Get room name from CLI arg, default to "meeting"
const room = process.argv[2] || "meeting";

// Set expiration (2 hours)
const now = Math.floor(Date.now() / 1000);
const exp = now + 120 * 60;

// JWT payload
const payload = {
  aud: "jitsi",
  iss: "chat",
  sub: "vpaas-magic-cookie-e515f4dfdbe24ae3a34c4247de2675db",
  room: room,
  iat: now,
  exp: exp,
  nbf: now,
  context: {
    user: {
      name: "ryan",
      email: "ryan@rykerrmedical.com",
      moderator: true
      avatar: ""
    },
    features: {
      livestreaming: true,
      recording: true,
      "outbound-call": true  // quotes fixed
    }
  }
};

// Sign token
const token = jwt.sign(payload, privateKey, {
  algorithm: "RS256",
  keyid: "vpaas-magic-cookie-e515f4dfdbe24ae3a34c4247de2675db/5758e1-SAMPLE_APP"
});

// Save token
fs.writeFileSync("token.txt", token);
console.log("✅ Token saved to token.txt");

// Show expiration in local time
console.log("⏰ Expires at:", new Date(exp * 1000).toLocaleString());

// Git commit + push
try {
  execSync("git add token.txt", { stdio: "inherit" });
  execSync(`git commit -m "Update JWT for room: ${room}"`, { stdio: "inherit" });
  execSync("git push", { stdio: "inherit" });
  console.log("🚀 token.txt committed & pushed to GitHub");
} catch (err) {
  console.error("⚠️ Git push failed. Make sure you set up git + SSH keys:", err.message);
}
