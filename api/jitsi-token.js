import jwt from 'jsonwebtoken';

export default async function handler(req, res) {
  // Enable CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  try {
    const { room = 'rykerrmedicalmeeting', password = '' } = req.query;
    
    const correctPassword = process.env.MODERATOR_PASSWORD;
    const isModerator = password === correctPassword;
    
    const privateKeyRaw = process.env.JITSI_PRIVATE_KEY;
    if (!privateKeyRaw) throw new Error('Missing JITSI_PRIVATE_KEY');
    
    const privateKey = privateKeyRaw; // Use as-is, already has real newlines
    const now = Math.floor(Date.now() / 1000);
    const exp = now + 2 * 60 * 60;
    
    const payload = {
      aud: 'jitsi',
      iss: 'chat',
      sub: 'vpaas-magic-cookie-e515f4dfdbe24ae3a34c4247de2675db',
      room: '*',
      iat: now,
      exp: exp,
      nbf: now,
      context: {
        user: {
          name: isModerator ? 'Ryan' : 'Guest',
          email: isModerator ? 'ryan@rykerrmedical.com' : '',
          moderator: isModerator ? 'true' : 'false',
          avatar: ''
        },
        features: {
          livestreaming: isModerator ? 'true' : 'false',
          recording: isModerator ? 'true' : 'false',
          'outbound-call': isModerator ? 'true' : 'false'
        }
      }
    };
    
    const keyid = 'vpaas-magic-cookie-e515f4dfdbe24ae3a34c4247de2675db/1e1dce';
    const token = jwt.sign(payload, privateKey, { algorithm: 'RS256', keyid });
    
    return res.status(200).json({ token });
  } catch (err) {
    console.error('JWT generation error:', err);
    return res.status(500).json({ error: err.message });
  }
}
