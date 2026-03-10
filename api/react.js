// Vercel Edge Function — viral-proof reaction counters via Upstash Redis
export const config = { runtime: 'edge' };

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Content-Type': 'application/json',
};

export default async function handler(req) {
  // CORS preflight
  if (req.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS });
  }

  const { searchParams } = new URL(req.url);
  const slug = searchParams.get('slug');
  const type = searchParams.get('type'); // 'love' | 'hate' | 'get'

  if (!slug) {
    return new Response(JSON.stringify({ error: 'slug required' }), { status: 400, headers: CORS });
  }

  const BASE = process.env.UPSTASH_REDIS_REST_URL;
  const TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN;

  if (!BASE || !TOKEN) {
    // Graceful degradation — return zeros, don't break the blog
    return new Response(JSON.stringify({ love: 0, hate: 0, degraded: true }), { headers: CORS });
  }

  const upstash = async (cmd) => {
    const r = await fetch(`${BASE}/${cmd}`, {
      headers: { Authorization: `Bearer ${TOKEN}` },
    });
    const j = await r.json();
    return parseInt(j.result || 0, 10) || 0;
  };

  // Increment if type is love or hate
  if (type === 'love' || type === 'hate') {
    await upstash(`incr/blog:${slug}:${type}`);
  }

  // Always return current counts
  const [love, hate] = await Promise.all([
    upstash(`get/blog:${slug}:love`),
    upstash(`get/blog:${slug}:hate`),
  ]);

  return new Response(JSON.stringify({ love, hate }), {
    headers: { ...CORS, 'Cache-Control': 'no-store' },
  });
}
