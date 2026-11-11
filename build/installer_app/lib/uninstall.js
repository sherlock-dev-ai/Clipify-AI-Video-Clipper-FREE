'use strict';

const fs = require('fs');
const path = require('path');

/** Remove only files that came from the bundled application payload. */
function removeBundledFiles(installDir, payloadRoot) {
  const installRoot = path.resolve(installDir);
  const payload = path.resolve(payloadRoot);
  const files = [];
  const directories = [];

  const walk = (directory, relative = '') => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      if (entry.isSymbolicLink()) continue;
      const rel = relative ? path.join(relative, entry.name) : entry.name;
      const full = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        directories.push(rel);
        walk(full, rel);
      } else if (entry.isFile()) {
        files.push(rel);
      }
    }
  };
  walk(payload);

  let removed = 0;
  let skipped = 0;
  const hasRedirectedParent = (destination) => {
    const parts = path.relative(installRoot, path.dirname(destination)).split(path.sep).filter(Boolean);
    let parent = installRoot;
    for (const part of parts) {
      parent = path.join(parent, part);
      try {
        if (fs.lstatSync(parent).isSymbolicLink()) return true;
      } catch (error) {
        if (error.code === 'ENOENT') return false;
        throw error;
      }
    }
    return false;
  };
  for (const relative of files) {
    const destination = path.resolve(installRoot, relative);
    const prefix = installRoot.endsWith(path.sep) ? installRoot : installRoot + path.sep;
    if (!destination.toLowerCase().startsWith(prefix.toLowerCase())) {
      skipped += 1;
      continue;
    }

    // Refuse to walk through a junction/symlink installed under the target.
    if (hasRedirectedParent(destination)) {
      skipped += 1;
      continue;
    }

    try {
      const stat = fs.lstatSync(destination);
      if (stat.isFile() || stat.isSymbolicLink()) {
        fs.unlinkSync(destination);
        removed += 1;
      } else {
        skipped += 1;
      }
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }

  // Remove empty application directories only; any remaining data keeps its
  // containing directory and remains untouched.
  for (const relative of directories.reverse()) {
    const destination = path.resolve(installRoot, relative);
    try {
      if (!hasRedirectedParent(destination) && !fs.lstatSync(destination).isSymbolicLink() &&
          fs.readdirSync(destination).length === 0) {
        fs.rmdirSync(destination);
      }
    } catch (error) {
      if (error.code !== 'ENOENT' && error.code !== 'ENOTEMPTY') throw error;
    }
  }

  return { removed, skipped };
}

module.exports = { removeBundledFiles };
