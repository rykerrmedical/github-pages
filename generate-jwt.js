const fs = require("fs");
const jwt = require("jsonwebtoken");
const { execSync } = require("child_process");

// Load your private key
const privateKey = fs.readFileSync("private.key", "utf8");
console.log("🔑 Private key loaded, length:", privateKey.length);
console.log("🔑 Private key starts with:", privateKey.substring(0, 50) + "...");

// Get room name from CLI arg, default to "mymeeting123"
const room = process.argv[2] || "mymeeting123";

// Set expiration (2 hours)
const now = Math.floor(Date.now() / 1000);
const exp = now + 120 * 60;

// JWT payload
const payload = {
  aud: "jitsi",
  iss: "chat",
  sub: "vpaas-magic-cookie-e515f4dfdbe24ae3a34c4247de2675db/1e1dce",
  room: "*",
  iat: now,
  exp: exp,
  nbf: now,
  context: {
    user: {
      name: "ryan",
      email: "ryan@rykerrmedical.com",
      moderator: true,
      avatar: ""
    },
    features: {
      livestreaming: true,
      recording: true,
      "outbound-call": true
    }
  }
};

console.log("📋 JWT Payload:", JSON.stringify(payload, null, 2));

const keyid = "vpaas-magic-cookie-e515f4dfdbe24ae3a34c4247de2675db/1e1dce";
console.log("🆔 Using keyid:", keyid);

// Sign token
const token = jwt.sign(payload, privateKey, {
  algorithm: "RS256",
  keyid: keyid
});

console.log("🔑 Generated JWT:", token);

// Decode and verify the header
const header = JSON.parse(Buffer.from(token.split('.')[0], 'base64').toString());
console.log("📋 JWT Header:", JSON.stringify(header, null, 2));

// Save token
fs.writeFileSync("assets/token.txt", token);
console.log("✅ Token saved to assets/token.txt");
console.log("🏠 Room name:", room);
console.log("⏰ Expires at:", new Date(exp * 1000).toLocaleString());

// Git commit + push
try {
  execSync("git add assets/token.txt", { stdio: "inherit" });
  execSync(`git commit -m "Update JWT for room: ${room}"`, { stdio: "inherit" });
  execSync("git push", { stdio: "inherit" });
  console.log("🚀 assets/token.txt committed & pushed to GitHub");
} catch (err) {
  console.error("⚠️ Git push failed:", err.message);
}
