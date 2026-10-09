import {build} from 'esbuild';
import {mkdir, readFile, writeFile, copyFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const site = path.resolve(root, '../../site');
await mkdir(path.join(root, 'public'), {recursive: true});
for (const name of ['index.html', 'privacy.html']) await copyFile(path.join(root, 'web', name), path.join(root, 'public', name));
await copyFile(path.join(site, 'icon.svg'), path.join(root, 'public/icon.svg'));
const css = await readFile(path.join(site, 'account.css'), 'utf8');
await writeFile(path.join(root, 'public/account.css'), css + '\n.methods{display:flex;gap:8px}.methods [aria-pressed=true]{border-color:var(--blue)}.submit{width:100%;margin:20px 0 8px}#recaptcha{margin-top:18px}.footnote{line-height:1.65}#welcome{font-size:18px;overflow-wrap:anywhere}\n');
const emulator = process.argv.includes('--emulator');
if (emulator) {
  const settings = JSON.parse(await readFile(path.join(root, 'firebase.json'), 'utf8'));
  const policy = settings.hosting.headers[0].headers.find(h => h.key === 'Content-Security-Policy');
  policy.value = policy.value.replace("connect-src 'self'", "connect-src 'self' http://127.0.0.1:19099");
  await writeFile(path.join(root, 'firebase.emulator.json'), JSON.stringify(settings, null, 2));
  await writeFile(path.join(root, 'functions/.env.local'), 'ACCOUNT_ORIGIN=http://127.0.0.1:15000\nPHONE_SIGNUP_ENABLED=true\n');
}
await writeFile(path.join(root, 'public/portal-config.json'), JSON.stringify(emulator ? {
  emulator: true, firebase: {apiKey: 'demo-cognesia-key', projectId: 'demo-cognesia-accounts', appId: 'demo-cognesia-app'}
} : {emulator: false}) + '\n');
await build({entryPoints: [path.join(root, 'web/account.js')], outfile: path.join(root, 'public/account.js'), bundle: true, minify: true, target: 'es2022', legalComments: 'eof'});
console.log('Built Cognesia account portal (' + (emulator ? 'loopback emulator' : 'production Firebase Hosting') + ').');
