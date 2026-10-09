import {readFile} from 'node:fs/promises';
const config = JSON.parse(await readFile(new URL('../public/portal-config.json', import.meta.url), 'utf8'));
if (config.emulator !== false || Object.keys(config).some(key=>!['emulator','firebase'].includes(key))
    || (config.firebase && (config.firebase.projectId !== 'cognesia-accounts'
      || config.firebase.authDomain !== 'cognesia-accounts.firebaseapp.com'
      || Object.keys(config.firebase).some(key=>!['apiKey','authDomain','projectId','appId'].includes(key))))) {
  throw new Error('Refusing to deploy an emulator build. Run npm run build first.');
}
console.log('Production portal configuration verified.');
