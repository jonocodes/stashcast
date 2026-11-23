// Shared Playwright launch options. Set CHROME to a Chromium binary when Playwright's
// bundled browser can't run (e.g. on NixOS: CHROME=$(ls -d /nix/store/*-playwright-chromium/*/chrome | head -1)).
export function launchOptions() {
  return process.env.CHROME ? { executablePath: process.env.CHROME } : {};
}
