// Install actual tarballs outside the workspace, then exercise ESM/CJS exports.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const archives = process.argv.slice(2).map((path) => resolve(path));
assert(archives.length, "Pass the package tarballs to test");
const manifests = archives.map((archive) =>
	JSON.parse(
		execFileSync("tar", ["-xOf", archive, "package/package.json"], {
			encoding: "utf8",
		}),
	),
);
const { packageManager } = JSON.parse(
	readFileSync(new URL("../package.json", import.meta.url), "utf8"),
);
const dependencies = {};
const overrides = {};
const imports = [];
for (const [index, manifest] of manifests.entries()) {
	const files = execFileSync("tar", ["-tzf", archives[index]], {
		encoding: "utf8",
	}).split("\n");
	const targets = (value) =>
		typeof value === "string" ? [value] : Object.values(value).flatMap(targets);
	for (const target of targets(manifest.exports)) {
		assert(
			target.startsWith("./dist/"),
			`Unbuilt export: ${manifest.name} ${target}`,
		);
		assert(
			files.includes(`package/${target.slice(2)}`),
			`Missing export: ${target}`,
		);
	}
	for (const version of Object.values(manifest.dependencies || {})) {
		assert(
			!version.startsWith("workspace:"),
			"pnpm must resolve workspace dependencies during pack",
		);
	}
	Object.assign(dependencies, manifest.peerDependencies);
	dependencies[manifest.name] = `file:${archives[index]}`;
	overrides[manifest.name] = `file:${archives[index]}`;
	imports.push(
		...Object.keys(manifest.exports).map(
			(key) => manifest.name + (key === "." ? "" : key.slice(1)),
		),
	);
}
const consumer = mkdtempSync(join(tmpdir(), "package-consumer-"));
writeFileSync(
	join(consumer, "package.json"),
	JSON.stringify(
		{
			private: true,
			type: "module",
			packageManager,
			dependencies,
			pnpm: { overrides },
		},
		null,
		2,
	),
);
execFileSync("pnpm", ["install", "--ignore-scripts"], {
	cwd: consumer,
	stdio: "inherit",
});
writeFileSync(
	join(consumer, "smoke.mjs"),
	`
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
for (const name of ${JSON.stringify(imports)}) {
  const esm = await import(name);
  const cjs = require(name);
  assert(Object.keys(esm).length > 0, name + ' ESM exports');
  assert(Object.keys(cjs).length > 0, name + ' CJS exports');
  assert(import.meta.resolve(name).includes('/dist/'), name + ' must resolve built files');
}
console.log('Installed tarball ESM/CJS exports passed');
`,
);
execFileSync(process.execPath, ["smoke.mjs"], {
	cwd: consumer,
	stdio: "inherit",
});
execFileSync(process.execPath, ["--conditions=development", "smoke.mjs"], {
	cwd: consumer,
	stdio: "inherit",
});
assert(
	readFileSync(join(consumer, "pnpm-lock.yaml"), "utf8").includes("integrity:"),
);
execFileSync("pnpm", ["install", "--frozen-lockfile", "--ignore-scripts"], {
	cwd: consumer,
	stdio: "inherit",
});
console.log(`Consumer evidence retained: ${consumer}`);
