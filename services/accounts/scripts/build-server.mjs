import {build} from 'esbuild';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
// Lambda disables require(ESM). Bundle the Admin Auth/jose dependency boundary
// into CommonJS, while leaving the Firestore transport to its own package.
await build({entryPoints:[root+'netlify/runtime.mjs'],outfile:root+'netlify/accounts-runtime.cjs',
  bundle:true,platform:'node',format:'cjs',target:'node24',external:['@google-cloud/firestore'],legalComments:'eof'});
const result=spawnSync(process.execPath,['--no-experimental-require-module','-e',
  "const m=require('./netlify/accounts-runtime.cjs');if(typeof m.default!=='function')process.exit(1)"],
  {cwd:root,stdio:'inherit',env:{...process.env,NODE_OPTIONS:''}});
if(result.status!==0)throw new Error('Account runtime cannot load with Lambda module restrictions.');
console.log('Account runtime bundled and import checked with Lambda module restrictions.');
