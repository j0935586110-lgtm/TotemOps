# Third-party browser parsers

These dependencies are bundled locally so folder triage still runs entirely in the browser.
No CDN, backend upload, network API, or mod JAR execution is required.

- **PrismarineJS / prismarine-nbt 2.8.0** — MIT; source: https://github.com/PrismarineJS/prismarine-nbt ; distributed as \`prismarine-nbt.min.js\` built with Browserify 17.0.1, including its transitive npm dependencies. Each constituent package retains its own license.
- **gildas-lormeau / zip.js 2.24.0** — BSD-3-Clause; source: https://github.com/gildas-lormeau/zip.js ; distributed as \`zip.min.js\`. See \`zip-LICENSE\` for the full notice.
- **squirrelchat / smol-toml 1.9.1** — BSD-3-Clause; source: https://github.com/squirrelchat/smol-toml ; bundled locally as \`toml.min.js\` (esbuild IIFE). See \`toml-LICENSE\`.
- **json5 / json5 2.2.3** — MIT; source: https://github.com/json5/json5 ; bundled locally as \`json5.min.js\`. See \`json5-LICENSE\`.

Parser output is advisory. ZIP archives are inspected through their central directory and allowlisted small manifest files. NBT and sampled Anvil chunks have compressed and expanded limits; configs are syntax-checked within strict byte limits. No parser is used to run Minecraft mods, expose config/NBT values, or write worlds.
