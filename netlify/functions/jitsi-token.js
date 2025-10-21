// /.netlify/functions/jitsi-token.js
import jwt from "jsonwebtoken";

export async function handler(event, context) {
  try {
    const { room } = JSON.parse(event.body || '{}');
    const roomName = room || "rykerrmedicalmeeting";

    const privateKeyRaw = process.env.JITSI_PRIVATE_KEY;
    if (!privateKeyRaw) throw new Error("Missing JITSI_PRIVATE_KEY");

    // convert \n to real line breaks
    const privateKey = privateKeyRaw.replace(/\\n/g, '\n');

    const now = Math.floor(Date.now() / 1000);
    const exp = now + 2 * 60 * 60; // 2 hours

    const payload = {
      aud: "jitsi",
      iss: "chat",
      sub: "vpaas-magic-cookie-e515f4dfdbe24ae3a34c4247de2675db",
      room: `vpaas-magic-cookie-e515f4dfdbe24ae3a34c4247de2675db/${roomName}`,
      iat: now,
      exp: exp,
      nbf: now,
      context: {
        user: {
          name: "Ryan",
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

    const keyid = "vpaas-magic-cookie-e515f4dfdbe24ae3a34c4247de2675db/1e1dce";

    const token = jwt.sign(payload, privateKey, {
      algorithm: "RS256",
      keyid: keyid
    });

    return {
      statusCode: 200,
      body: JSON.stringify({ token })
    };
  } catch (err) {
    console.error("JWT generation error:", err);
    return {
      statusCode: 500,
      body: JSON.stringify({ error: err.message })
    };
  }
}


