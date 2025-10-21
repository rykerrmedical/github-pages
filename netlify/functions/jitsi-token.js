// /.netlify/functions/jitsi-token.js
import jwt from "jsonwebtoken"; // make sure to install in your function

export async function handler(event, context) {
  try {
    const { room } = JSON.parse(event.body);

    // Replace these with your Jitsi/JAAS credentials
    const apiKey = process.env.JITSI_API_KEY;
    const apiSecret = process.env.JITSI_API_SECRET;

      const payload = {
        aud: "jitsi",
        iss: apiKey,
        sub: "vpaas-magic-cookie-e515f4dfdbe24ae3a34c4247de2675db", // ✅ your JAAS tenant
        room: `vpaas-magic-cookie-e515f4dfdbe24ae3a34c4247de2675db/${room}`,
        exp: Math.floor(Date.now() / 1000) + 60 * 60
      };

    const token = jwt.sign(payload, apiSecret);

    return {
      statusCode: 200,
      body: JSON.stringify({ token })
    };
  } catch (err) {
    console.error(err);
    return {
      statusCode: 500,
      body: JSON.stringify({ error: "Could not generate token" })
    };
  }
}

