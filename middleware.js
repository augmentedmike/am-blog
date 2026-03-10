// Vercel Middleware — old-slug → new-path redirects
// Date gating is handled by the homepage JS filter (CT timezone).
// Direct post URLs are always accessible — no server-side date blocking.

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
    // pass through on fetch failure
  }
  return manifestCache;
}

export default async function middleware(req) {
  const url = new URL(req.url);
  const path = url.pathname;

  // ── 1. Old-slug redirect: /NNN-some-slug/ → /thoughts/NNN/seo-title/en/
  const oldMatch = path.match(/^\/(\d{3}-[^/]+)(\/.*)?$/);
  if (oldMatch) {
    const slug = oldMatch[1];
    const rest = oldMatch[2] || '/';

    // Always serve assets directly — don't redirect images, css, js, etc.
    const isAsset = rest.match(/\.(jpg|jpeg|png|gif|webp|svg|css|js|json|txt|xml|ico)$/i);
    if (isAsset) return;

    const manifest = await loadManifest(url.origin);
    if (manifest) {
      const post = manifest.posts.find(p => p.slug === slug);
      if (post) {
        const newPath = `/${post.seo_path}/en/`;
        return Response.redirect(new URL(newPath, url.origin).toString(), 301);
      }
    }
    return; // unknown old-slug, pass through
  }

  // ── 2. New-path: /thoughts/NNN/seo-title/ → redirect bare path to /en/
  const newMatch = path.match(/^\/thoughts\/(\d{3})\/([^/]+)(\/.*)?$/);
  if (newMatch) {
    const episode = newMatch[1];
    const seoTitle = newMatch[2];
    const rest = newMatch[3] || '/';

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
