// Vercel Middleware — future-date gating + old-slug → new-path redirects
// Runs at the edge on every request matching the config.matcher pattern.

let manifestCache = null;
let manifestFetchedAt = 0;
const CACHE_TTL = 5 * 60 * 1000; // 5 minutes

async function loadManifest(origin) {
  const now = Date.now();
  if (manifestCache && now - manifestFetchedAt < CACHE_TTL) return manifestCache;
  try {
    const res = await fetch(`${origin}/posts-manifest.json`);
    if (res.ok) {
      manifestCache = await res.json();
      manifestFetchedAt = now;
    }
  } catch {
    // pass through on fetch failure — don't block published posts
  }
  return manifestCache;
}

export default async function middleware(req) {
  const url = new URL(req.url);
  const path = url.pathname;

  const manifest = await loadManifest(url.origin);
  const today = new Date().toISOString().slice(0, 10);

  // ── 1. Old-slug redirect: /NNN-some-slug/ → /thoughts/NNN/seo-title/en/
  const oldMatch = path.match(/^\/(\d{3}-[^/]+)(\/.*)?$/);
  if (oldMatch) {
    const slug = oldMatch[1];
    if (manifest) {
      const post = manifest.posts.find(p => p.slug === slug);
      if (post) {
        // Gate future posts even on old URLs
        if (post.date > today) {
          return new Response('Not Found', { status: 404, headers: { 'Content-Type': 'text/plain' } });
        }
        // Redirect to canonical new URL
        const newPath = `/${post.seo_path}/en/`;
        return Response.redirect(new URL(newPath, url.origin).toString(), 301);
      }
    }
    return; // unknown old-slug, pass through
  }

  // ── 2. New-path gating: /thoughts/NNN/seo-title/(en|es|assets...)
  const newMatch = path.match(/^\/thoughts\/(\d{3})\/([^/]+)(\/.*)?$/);
  if (newMatch) {
    const episode = newMatch[1];
    const seoTitle = newMatch[2];
    const rest = newMatch[3] || '/';

    if (manifest) {
      const post = manifest.posts.find(p => p.seo_path === `thoughts/${episode}/${seoTitle}`);
      if (post && post.date > today) {
        return new Response('Not Found', { status: 404, headers: { 'Content-Type': 'text/plain' } });
      }
    }

    // Bare /thoughts/NNN/seo-title/ → redirect to /en/
    if (rest === '/' || rest === '') {
      return Response.redirect(new URL(`/thoughts/${episode}/${seoTitle}/en/`, url.origin).toString(), 302);
    }

    return; // pass through to static file serving
  }

  return; // not a post URL
}

export const config = {
  matcher: [
    // Old slug format: /NNN-slug/...
    '/:path(\\d{3}-[^/]+)/:rest*',
    '/:path(\\d{3}-[^/]+)',
    // New thoughts format: /thoughts/NNN/title/...
    '/thoughts/:episode(\\d{3})/:title/:rest*',
    '/thoughts/:episode(\\d{3})/:title',
  ],
};
