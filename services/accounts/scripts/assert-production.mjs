import {readFile} from 'node:fs/promises';
const config = JSON.parse(await readFile(new URL('../public/portal-config.json', import.meta.url), 'utf8'));
if (JSON.stringify(config) !== JSON.stringify({emulator: false})) {
  throw new Error('Refusing to deploy an emulator build. Run npm run build first.');
}
console.log('Production portal configuration verified.');
