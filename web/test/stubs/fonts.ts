// Test stand-in for @remotion/fonts: the composition registers its subtitle font on import,
// and jsdom cannot fetch Vite asset URLs.
export const loadFont = () => Promise.resolve();
