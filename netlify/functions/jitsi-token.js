// /.netlify/functions/jitsi-token.js
import jwt from "jsonwebtoken";

export async function handler(event) {
  try {
    const room = event.queryStringParameters?.room || "rykerrmedicalmeeting";

    const privateKeyRaw = process.env.JITSI_PRIVATE_KEY;
    if (!privateKeyRaw) throw new Error("Missing JITSI_PRIVATE_KEY");
    const privateKey = privateKeyRaw.replace(/\\n/g, "\n");

    const now = Math.floor(Date.now() / 1000);
    const exp = now + 2 * 60 * 60;

    const payload = {
      aud: "jitsi",
      iss: "vpaas-magic-cookie-e515f4dfdbe24ae3a34c4247de2675db",
      sub: "8x8.vc",
      room: `vpaas-magic-cookie-e515f4dfdbe24ae3a34c4247de2675db/${room}`,
      iat: now,
      exp: exp,
      nbf: now,
      context: {
        user: { name: "Ryan", email: "ryan@rykerrmedical.com", moderator: true, avatar: "" },
        features: { livestreaming: true, recording: true, "outbound-call": true }
      }
    };

    const keyid = "vpaas-magic-cookie-e515f4dfdbe24ae3a34c4247de2675db/1e1dce";
    const token = jwt.sign(payload, privateKey, { algorithm: "RS256", keyid });

    return {
      statusCode: 200,
      headers: { "Access-Control-Allow-Origin": "*" }, // ⚡ Add this
      body: JSON.stringify({ token })
    };
  } catch (err) {
    console.error("JWT generation error:", err);
    return {
      statusCode: 500,
      headers: { "Access-Control-Allow-Origin": "*" },
      body: JSON.stringify({ error: err.message })
    };
  }
}



