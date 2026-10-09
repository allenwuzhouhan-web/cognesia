import serverless from 'serverless-http';

const security = {'Cache-Control':'no-store, max-age=0','Content-Type':'application/json',
  'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY'};
const failure = (message, status) => new Response(JSON.stringify({error:{message}}), {status,headers:security});

export function countryPolicy(value) {
  if (value === undefined) throw new Error('Country policy must be explicitly configured.');
  const codes = value.split(',').map(s=>s.trim().toUpperCase()).filter(Boolean);
  if (codes.some(code=>!/^([A-Z]{2})$/.test(code))) throw new Error('Invalid country policy.');
  return new Set(codes);
}

// Netlify's trusted context supplies location and IP. Never trust client headers.
export function makeNetlifyHandler(app, {origin, blockedCountries = new Set()}) {
  if (!/^https:\/\/[^/]+$/.test(origin)) throw new Error('Expected the canonical HTTPS origin.');
  const invoke = serverless(app, {provider:'aws'});
  return async (request, context) => {
    const url = new URL(request.url);
    if (url.origin !== origin) return failure('Use the official Cognesia account website.',403);
    if (blockedCountries.size) {
      const country = context.geo?.country?.code;
      if (!/^[A-Z]{2}$/.test(country || '') || ['ZZ','XX'].includes(country) || blockedCountries.has(country)) {
        return failure('Cognesia account access is unavailable from this location.',403);
      }
    }
    let body = Buffer.alloc(0);
    if (request.body) {
      const reader = request.body.getReader();
      try {
        while (true) {
          const {done,value} = await reader.read();
          if (done) break;
          if (body.length + value.length > 2048) { await reader.cancel(); return failure('Invalid account request.',413); }
          body = Buffer.concat([body,Buffer.from(value)]);
        }
      } finally { reader.releaseLock(); }
    }
    const headers = Object.fromEntries(request.headers);
    // The platform IP becomes the adapter socket address used by the app limiter.
    delete headers['x-forwarded-for'];
    const result = await invoke({version:'2.0',rawPath:url.pathname,rawQueryString:url.search.slice(1),
      headers,requestContext:{http:{method:request.method,path:url.pathname,sourceIp:context.ip || 'unknown',protocol:'HTTP/1.1'}},
      body:body.length?body.toString('base64'):undefined,isBase64Encoded:true},{});
    const outputHeaders = new Headers(result.headers);
    for (const [key,value] of Object.entries(security)) outputHeaders.set(key,value);
    return new Response(request.method==='HEAD'?null:result.isBase64Encoded?Buffer.from(result.body,'base64'):result.body,
      {status:result.statusCode,headers:outputHeaders});
  };
}
