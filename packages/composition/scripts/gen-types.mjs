import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { compileFromFile } from "json-schema-to-typescript";

const schemaPath = fileURLToPath(new URL("../schema/project.schema.json", import.meta.url));
const outputPath = fileURLToPath(new URL("../src/types.generated.ts", import.meta.url));

const banner = `/* eslint-disable */
// Generated from schema/project.schema.json by \`corepack pnpm gen:types\`. Do not edit.
// Regenerate the schema with \`uv run python -m powereditor.schema_gen\` in backend/.`;

const generated = await compileFromFile(schemaPath, {
  bannerComment: banner,
  additionalProperties: false,
  unreachableDefinitions: true,
  style: { printWidth: 100, singleQuote: false, trailingComma: "all" },
});

if (process.argv.includes("--check")) {
  const current = await readFile(outputPath, "utf8").then(
    (text) => text.replaceAll("\r\n", "\n"),
    () => null,
  );
  if (current !== generated) {
    console.error(`${outputPath} is stale; run \`corepack pnpm gen:types\`.`);
    process.exit(1);
  }
} else {
  await writeFile(outputPath, generated, "utf8");
}
