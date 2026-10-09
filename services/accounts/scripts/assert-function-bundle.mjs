import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
const zip=fileURLToPath(new URL('../.netlify/functions/accounts.zip',import.meta.url));
const temp=await mkdtemp(join(tmpdir(),'cognesia-function-check-'));
try {
  const unpack=spawnSync('unzip',['-q',zip,'-d',temp],{stdio:'inherit'});
  if(unpack.status!==0)throw new Error('Function archive could not be unpacked.');
  const entry=await readFile(join(temp,'___netlify-entry-point.mjs'),'utf8');
  const match=entry.match(/getLambdaHandler\('([./\w-]+\.mjs)'\)/);
  if(!match || match[1].includes('..'))throw new Error('Unexpected function entry point.');
  const code="const {default:handler}=await import("+JSON.stringify(join(temp,match[1]))+");if(typeof handler!=='function')throw new Error('Missing handler');const r=await handler(new Request('https://accounts.example.test/api/config'),{});if(r.status!==503)throw new Error('Unconfigured service must fail closed');console.log('Packaged function loads with Lambda module restrictions and fails closed without credentials.');";
  const check=spawnSync(process.execPath,['--no-experimental-require-module','--input-type=module','-e',code],
    {cwd:temp,stdio:'inherit',env:{...process.env,NODE_OPTIONS:'',COGNESIA_FIREBASE_SERVICE_ACCOUNT:''}});
  if(check.status!==0)throw new Error('Packaged function startup check failed.');
} finally {await rm(temp,{recursive:true,force:true});}
