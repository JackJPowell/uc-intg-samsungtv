/**
 * SmartThings OAuth Sub-Worker
 *
 * Handles OAuth flow for one SmartThings app registration.
 * The redirect_uri is derived dynamically from the incoming request origin
 * so the same code runs unchanged on smartthings1, smartthings2, etc.
 *
 * Environment variables required (set per-worker in Cloudflare dashboard):
 *   SMARTTHINGS_CLIENT_ID
 *   SMARTTHINGS_CLIENT_SECRET
 */

export default {
    async fetch(request, env) {
        const url = new URL(request.url);

        // Derive this worker's own base URL from the incoming request.
        // This means redirect_uri automatically matches whichever subdomain
        // is handling the request — no hardcoded URLs needed.
        const workerBase = `${url.protocol}//${url.host}`;
        const redirectUri = `${workerBase}/oauth/callback`;

        const corsHeaders = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
        };

        if (request.method === 'OPTIONS') {
            return new Response(null, { headers: corsHeaders });
        }

        // Route: GET /authorize
        if (url.pathname === '/authorize' && request.method === 'GET') {
            const state = crypto.randomUUID();

            const authUrl = new URL('https://api.smartthings.com/oauth/authorize');
            authUrl.searchParams.set('client_id', env.SMARTTHINGS_CLIENT_ID);
            authUrl.searchParams.set('redirect_uri', redirectUri);
            authUrl.searchParams.set('response_type', 'code');
            authUrl.searchParams.set('scope', 'r:devices:* x:devices:* r:installedapps');
            authUrl.searchParams.set('state', state);

            return new Response(JSON.stringify({
                authorizationUrl: authUrl.toString(),
                state: state,
                redirectUri: redirectUri,
            }), {
                headers: { 'Content-Type': 'application/json', ...corsHeaders },
            });
        }

        // Route: GET /oauth/callback
        if (url.pathname === '/oauth/callback' && request.method === 'GET') {
            const code = url.searchParams.get('code');
            const error = url.searchParams.get('error');

            if (error) {
                return new Response(`
          <!DOCTYPE html>
          <html>
          <head>
            <title>SmartThings OAuth - Error</title>
            <style>
              body { font-family: Arial, sans-serif; padding: 40px; max-width: 600px; margin: 0 auto; }
              .error { background: #fee; border: 1px solid #fcc; padding: 20px; border-radius: 5px; }
            </style>
          </head>
          <body>
            <h1>Authorization Failed</h1>
            <div class="error">
              <p><strong>Error:</strong> ${error}</p>
              <p><strong>Description:</strong> ${url.searchParams.get('error_description') || 'Unknown error'}</p>
            </div>
            <p>Please close this window and try again.</p>
          </body>
          </html>
        `, { headers: { 'Content-Type': 'text/html' } });
            }

            if (!code) {
                return new Response('Missing authorization code', { status: 400 });
            }

            try {
                const tokenResponse = await fetch('https://api.smartthings.com/oauth/token', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'Authorization': 'Basic ' + btoa(`${env.SMARTTHINGS_CLIENT_ID}:${env.SMARTTHINGS_CLIENT_SECRET}`),
                    },
                    body: new URLSearchParams({
                        grant_type: 'authorization_code',
                        code: code,
                        redirect_uri: redirectUri, // Must match exactly what was sent in /authorize
                    }),
                });

                if (!tokenResponse.ok) {
                    const errorText = await tokenResponse.text();
                    throw new Error(`Token exchange failed: ${tokenResponse.status} - ${errorText}`);
                }

                const tokens = await tokenResponse.json();

                return new Response(`
          <!DOCTYPE html>
          <html>
          <head>
            <title>SmartThings OAuth - Success</title>
            <style>
              body { font-family: Arial, sans-serif; padding: 40px; max-width: 800px; margin: 0 auto; }
              .success { background: #efe; border: 1px solid #cfc; padding: 20px; border-radius: 5px; margin-bottom: 20px; }
              .tokens { background: #f5f5f5; border: 1px solid #ddd; padding: 15px; border-radius: 5px; margin: 10px 0; }
              .token-item { margin: 15px 0; }
              .token-label { font-weight: bold; color: #333; margin-bottom: 5px; }
              .token-value { background: white; border: 1px solid #ccc; padding: 10px; border-radius: 3px; font-family: monospace; word-break: break-all; }
              button { background: #0066cc; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; font-size: 14px; margin-top: 10px; }
              button:hover { background: #0052a3; }
              .copied { background: #4CAF50 !important; }
              .instructions { background: #fff3cd; border: 1px solid #ffc107; padding: 15px; border-radius: 5px; margin-top: 20px; }
            </style>
            <script>
              function copyAllAsJSON() {
                const data = {
                  access_token: document.getElementById('access_token').textContent,
                  refresh_token: document.getElementById('refresh_token').textContent
                };
                navigator.clipboard.writeText(JSON.stringify(data, null, 2)).then(() => {
                  const btn = document.getElementById('copy_json');
                  btn.textContent = 'Copied!';
                  btn.classList.add('copied');
                  setTimeout(() => { btn.textContent = 'Copy as JSON'; btn.classList.remove('copied'); }, 2000);
                });
              }
            </script>
          </head>
          <body>
            <h1>Authorization Successful!</h1>
            <div class="success">
              <p>Your SmartThings OAuth tokens have been generated successfully.</p>
            </div>
            <div class="tokens">
              <h2>Your Tokens</h2>
              <div class="token-item">
                <div class="token-label">Access Token:</div>
                <div class="token-value" id="access_token">${tokens.access_token}</div>
              </div>
              <div class="token-item">
                <div class="token-label">Refresh Token:</div>
                <div class="token-value" id="refresh_token">${tokens.refresh_token}</div>
              </div>
              <div class="token-item">
                <button onclick="copyAllAsJSON()" id="copy_json">Copy as JSON</button>
              </div>
            </div>
            <div class="instructions">
              <h3>Next Steps:</h3>
              <ol>
                <li>Click Copy as JSON</li>
                <li>Paste the contents into your Remote integration setup</li>
                <li>The access token expires in ${Math.floor(tokens.expires_in / 3600)} hours but will be automatically refreshed</li>
              </ol>
            </div>
          </body>
          </html>
        `, { headers: { 'Content-Type': 'text/html' } });

            } catch (err) {
                return new Response(`
          <!DOCTYPE html>
          <html>
          <head>
            <title>SmartThings OAuth - Error</title>
            <style>
              body { font-family: Arial, sans-serif; padding: 40px; max-width: 600px; margin: 0 auto; }
              .error { background: #fee; border: 1px solid #fcc; padding: 20px; border-radius: 5px; }
            </style>
          </head>
          <body>
            <h1>Token Exchange Failed</h1>
            <div class="error"><p><strong>Error:</strong> ${err.message}</p></div>
            <p>Please try again or contact support.</p>
          </body>
          </html>
        `, { headers: { 'Content-Type': 'text/html' }, status: 500 });
            }
        }

        // Route: POST /refresh
        if (url.pathname === '/refresh' && request.method === 'POST') {
            try {
                const body = await request.json();
                const refreshToken = body.refresh_token;

                if (!refreshToken) {
                    return new Response(JSON.stringify({ error: 'Missing refresh_token' }), {
                        status: 400,
                        headers: { 'Content-Type': 'application/json', ...corsHeaders },
                    });
                }

                const tokenResponse = await fetch('https://api.smartthings.com/oauth/token', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'Authorization': 'Basic ' + btoa(`${env.SMARTTHINGS_CLIENT_ID}:${env.SMARTTHINGS_CLIENT_SECRET}`),
                    },
                    body: new URLSearchParams({
                        grant_type: 'refresh_token',
                        refresh_token: refreshToken,
                    }),
                });

                if (!tokenResponse.ok) {
                    const errorText = await tokenResponse.text();
                    return new Response(JSON.stringify({ error: 'Token refresh failed', details: errorText }), {
                        status: tokenResponse.status,
                        headers: { 'Content-Type': 'application/json', ...corsHeaders },
                    });
                }

                const tokens = await tokenResponse.json();
                return new Response(JSON.stringify(tokens), {
                    headers: { 'Content-Type': 'application/json', ...corsHeaders },
                });

            } catch (err) {
                return new Response(JSON.stringify({ error: 'Internal server error', message: err.message }), {
                    status: 500,
                    headers: { 'Content-Type': 'application/json', ...corsHeaders },
                });
            }
        }

        return new Response('Not Found', { status: 404, headers: corsHeaders });
    }
};
