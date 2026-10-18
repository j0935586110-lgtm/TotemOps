# Third-party browser parsers

These dependencies are bundled locally so folder triage still runs entirely in the browser.
No CDN, backend upload, network API, or mod JAR execution is required.

- **PrismarineJS / prismarine-nbt 2.8.0** — MIT; source: https://github.com/PrismarineJS/prismarine-nbt ; distributed as \`prismarine-nbt.min.js\` built with Browserify 17.0.1, including its transitive npm dependencies. Each constituent package retains its own license.
- **gildas-lormeau / zip.js 2.24.0** — BSD-3-Clause; source: https://github.com/gildas-lormeau/zip.js ; distributed as \`zip.min.js\`. See \`zip-LICENSE\` for the full notice.

Parser output is advisory. ZIP archives are read through their central directory and allowlisted small metadata files; NBT files are bounded before and after decompression. Neither parser is used to run Minecraft mods or write worlds.
