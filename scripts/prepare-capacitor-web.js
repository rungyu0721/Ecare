const fs = require("fs");
const path = require("path");

const root = process.cwd();
const outDir = path.join(root, "www");

const includeFiles = [
  "index.html",
  "user.html",
  "ecare.html",
  "records.html",
  "profile.html",
  "app.js",
  "ecare.js",
  "records.js",
  "profile.js",
  "styles.css",
  "ecare.css",
  "profile.css",
  "manifest.json",
  "sw.js"
];

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function copyIfExists(relPath) {
  const src = path.join(root, relPath);
  if (!fs.existsSync(src)) return;
  const dest = path.join(outDir, relPath);
  ensureDir(path.dirname(dest));
  fs.copyFileSync(src, dest);
}

function copyDirIfExists(relDir) {
  const srcDir = path.join(root, relDir);
  if (!fs.existsSync(srcDir)) return;

  const walk = (currentSrc, currentDest) => {
    ensureDir(currentDest);
    for (const entry of fs.readdirSync(currentSrc, { withFileTypes: true })) {
      const srcPath = path.join(currentSrc, entry.name);
      const destPath = path.join(currentDest, entry.name);
      if (entry.isDirectory()) {
        walk(srcPath, destPath);
      } else {
        fs.copyFileSync(srcPath, destPath);
      }
    }
  };

  walk(srcDir, path.join(outDir, relDir));
}

fs.rmSync(outDir, { recursive: true, force: true });
ensureDir(outDir);

for (const file of includeFiles) {
  copyIfExists(file);
}

copyDirIfExists("icons");

console.log("Prepared Capacitor web assets in www/");
