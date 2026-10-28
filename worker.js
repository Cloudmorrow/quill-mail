// The Worker Mail puts in your Cloudflare account, under the name Settings
// shows: Email Routing hands it every mail for the domain, and it puts the
// mail, as it came, into a KV namespace. The server pulls from there every
// minute, through Cloudflare's API, so a cloud on a home network with no
// address from outside gets its mail all the same. Nothing is parsed here
// and nothing is sent from here; a mail waits two weeks at most.
export default {
  async email(message, env) {
    const raw = new Uint8Array(await new Response(message.raw).arrayBuffer());
    const cap = 1500000;
    const bytes = raw.length > cap ? raw.subarray(0, cap) : raw;
    let text = "";
    for (let i = 0; i < bytes.length; i += 32768) {
      text += String.fromCharCode.apply(null, bytes.subarray(i, i + 32768));
    }
    const key = `${Date.now()}-${crypto.randomUUID()}`;
    const kept = {
      from: message.from,
      to: message.to,
      size: raw.length,
      cut: raw.length > cap,
      received: new Date().toISOString(),
      raw: btoa(text),
    };
    await env.MAIL.put(key, JSON.stringify(kept), { expirationTtl: 14 * 24 * 60 * 60 });
  },
};
