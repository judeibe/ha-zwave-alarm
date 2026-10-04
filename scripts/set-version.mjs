// Sets the release version in the integration manifest. Usage: node scripts/set-version.mjs 1.2.3
import { readFileSync, writeFileSync } from 'node:fs';

const version = process.argv[2];
if (!/^\d+\.\d+\.\d+$/.test(version ?? '')) {
  console.error('usage: node scripts/set-version.mjs <major.minor.patch>');
  process.exit(1);
}
// Text edit, not JSON round-trip, so the hand-formatted manifest keeps its layout.
const manifest = 'custom_components/zwave_alarm/manifest.json';
writeFileSync(manifest, readFileSync(manifest, 'utf8').replace(/("version":\s*")[^"]*"/, `$1${version}"`));
console.log(`version set to ${version}`);
