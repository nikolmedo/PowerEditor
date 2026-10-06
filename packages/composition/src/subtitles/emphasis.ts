/**
 * Word picks of the `editorial_emphasis` and `emoji_pop` presets. Both are deterministic, so
 * the Player and the render (and every re-render) mark the same words.
 */

/**
 * Function words of Spanish and English. A project does not store its language, so both lists
 * apply at once; a Spanish stopword is rarely an English content word and vice versa.
 */
const STOPWORDS = new Set([
  // Spanish
  "algo", "alguien", "aquí", "así", "aunque", "cada", "como", "cómo", "con", "contra", "cual",
  "cuál", "cuando", "cuándo", "desde", "donde", "dónde", "durante", "ella", "ellas", "ellos",
  "entonces", "entre", "esta", "está", "estaba", "estamos", "están", "estar", "este", "esto",
  "estos", "estas", "hacer", "hace", "hacia", "hasta", "hay", "luego", "mientras", "mismo",
  "mucho", "muchos", "muchas", "muy", "nada", "nosotros", "otra", "otro", "otros", "para",
  "pero", "poco", "porque", "puede", "pues", "quien", "quién", "sobre", "solo", "sólo",
  "también", "tanto", "tener", "tiene", "tienen", "todo", "todos", "todas", "vamos", "ustedes",
  "vosotros", "yo", "eso", "esos", "esas", "ese", "aquel", "somos", "eres", "fueron",
  // English
  "about", "above", "after", "again", "also", "because", "been", "before", "being", "below",
  "between", "both", "could", "does", "doing", "down", "during", "each", "from", "further",
  "have", "having", "here", "into", "just", "more", "most", "only", "other", "over", "same",
  "should", "some", "such", "than", "that", "their", "them", "then", "there", "these", "they",
  "this", "those", "through", "under", "until", "very", "want", "were", "what", "when", "where",
  "which", "while", "will", "with", "would", "your", "yours", "really", "gonna", "thing",
]); // prettier-ignore

/** Shorter words never carry the emphasis. */
const MIN_EMPHASIS_LETTERS = 4;
/** Lines this short read as one beat already; emphasis would land on most of them. */
const MIN_WORDS_FOR_EMPHASIS = 3;

const EDGE_PUNCTUATION = /^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu;

function bareWord(text: string): string {
  return text.replace(EDGE_PUNCTUATION, "").toLocaleLowerCase();
}

/**
 * Index of the one word to emphasize in a line, or -1: the longest word that is not a
 * stopword, the first one on a tie. Lines under three words get none, so emphasis stays rare.
 */
export function emphasizedWordIndex(words: readonly string[]): number {
  if (words.length < MIN_WORDS_FOR_EMPHASIS) return -1;
  let best = -1;
  let bestLength = MIN_EMPHASIS_LETTERS - 1;
  words.forEach((text, index) => {
    const word = bareWord(text);
    const length = [...word].length;
    if (length > bestLength && !STOPWORDS.has(word)) {
      best = index;
      bestLength = length;
    }
  });
  return best;
}

/** Pictographic emoji (with presentation, or forced by VS16); not `©`, `#` or digits. */
const EMOJI = /\p{Emoji_Presentation}|\p{Extended_Pictographic}️/u;

/** Whether `text` carries an emoji. `emoji_pop` animates only these; it never adds any. */
export function hasEmoji(text: string): boolean {
  return EMOJI.test(text);
}
