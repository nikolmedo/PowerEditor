import composition from "./composition.json";

/**
 * Id of the registered composition. Lives in `composition.json` so that
 * `scripts/render.mjs`, which runs as plain Node without a TypeScript loader,
 * reads the same value.
 */
export const COMPOSITION_ID: string = composition.id;
