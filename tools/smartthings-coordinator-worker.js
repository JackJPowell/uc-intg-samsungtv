/**
 * SmartThings OAuth Coordinator - Cloudflare Worker
 *
 * Routes new users to the least-full sub-worker.
 * Each sub-worker has its own SmartThings app with a 20-user limit.
 *
 * KV binding required: SMARTTHINGS_USERS
 *   KV keys: "count:smartthings1.jackattack51.workers.dev", etc.
 *
 * Environment variables:
 *   WORKER_HOSTS - comma-separated sub-worker base URLs, e.g.:
 *                  "https://smartthings1.jackattack51.workers.dev,https://smartthings2.jackattack51.workers.dev"
 *   WORKER_CAPACITY - max users per worker (default: 20)
 */

const DEFAULT_CAPACITY = 20;

export default {
    async fetch(request, env) {
        const url = new URL(request.url);

        const corsHeaders = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
        };

        if (request.method === 'OPTIONS') {
            return new Response(null, { headers: corsHeaders });
        }

        // Route: GET /authorize
        // Picks the least-full sub-worker, increments its count, and builds the
        // authorization URL directly (Cloudflare Workers cannot fetch other
        // workers.dev URLs, so we inline the logic here rather than forwarding).
        if (url.pathname === '/authorize' && request.method === 'GET') {
            const hosts = (env.WORKER_HOSTS || '').split(',').map(h => h.trim()).filter(Boolean);
            const capacity = parseInt(env.WORKER_CAPACITY || String(DEFAULT_CAPACITY), 10);

            if (hosts.length === 0) {
                return new Response(JSON.stringify({ error: 'No sub-workers configured' }), {
                    status: 503,
                    headers: { 'Content-Type': 'application/json', ...corsHeaders },
                });
            }

            // Read current user counts for all workers from KV
            const counts = await Promise.all(
                hosts.map(async (host) => {
                    const key = `count:${new URL(host).hostname}`;
                    const val = await env.SMARTTHINGS_USERS.get(key);
                    return { host, key, count: val ? parseInt(val, 10) : 0 };
                })
            );

            // Pick the sub-worker with the lowest count that still has capacity
            const available = counts.filter(w => w.count < capacity);
            if (available.length === 0) {
                return new Response(JSON.stringify({ error: 'All sub-workers are at capacity' }), {
                    status: 503,
                    headers: { 'Content-Type': 'application/json', ...corsHeaders },
                });
            }

            const chosen = available.reduce((a, b) => a.count <= b.count ? a : b);

            // Look up the client_id for this sub-worker.
            // Env vars are named SMARTTHINGS_CLIENT_ID_1, _2, _3, _4 matching
            // the sub-worker index in WORKER_HOSTS (1-based).
            const workerIndex = hosts.indexOf(chosen.host) + 1;
            const clientId = env[`SMARTTHINGS_CLIENT_ID_${workerIndex}`];

            if (!clientId) {
                return new Response(JSON.stringify({ error: `No client_id configured for worker ${workerIndex}` }), {
                    status: 503,
                    headers: { 'Content-Type': 'application/json', ...corsHeaders },
                });
            }

            // Build the redirect_uri using the chosen sub-worker's own origin
            const chosenUrl = new URL(chosen.host);
            const redirectUri = `${chosenUrl.protocol}//${chosenUrl.host}/oauth/callback`;
            const state = crypto.randomUUID();

            const authUrl = new URL('https://api.smartthings.com/oauth/authorize');
            authUrl.searchParams.set('client_id', clientId);
            authUrl.searchParams.set('redirect_uri', redirectUri);
            authUrl.searchParams.set('response_type', 'code');
            authUrl.searchParams.set('scope', 'r:devices:* x:devices:* r:installedapps');
            authUrl.searchParams.set('state', state);

            // Increment count now that we have a valid assignment
            await env.SMARTTHINGS_USERS.put(chosen.key, String(chosen.count + 1));

            return new Response(JSON.stringify({
                authorizationUrl: authUrl.toString(),
                state: state,
                redirectUri: redirectUri,
                workerUrl: chosen.host,
            }), {
                headers: { 'Content-Type': 'application/json', ...corsHeaders },
            });
        }

        // Route: GET / — status page showing capacity across all workers
        if (url.pathname === '/' && request.method === 'GET') {
            const hosts = (env.WORKER_HOSTS || '').split(',').map(h => h.trim()).filter(Boolean);
            const capacity = parseInt(env.WORKER_CAPACITY || String(DEFAULT_CAPACITY), 10);
            const counts = await Promise.all(
                hosts.map(async (host) => {
                    const key = `count:${new URL(host).hostname}`;
                    const val = await env.SMARTTHINGS_USERS.get(key);
                    return { host, count: val ? parseInt(val, 10) : 0, capacity };
                })
            );
            return new Response(JSON.stringify({ workers: counts }, null, 2), {
                headers: { 'Content-Type': 'application/json', ...corsHeaders },
            });
        }

        return new Response('Not Found', { status: 404, headers: corsHeaders });
    }
};
