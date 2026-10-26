// An emoji for a food, matched on a keyword in its name (Danish or English),
// first match wins — so "Sweet potatoes" hits 🍠 before "potato" hits 🥔.
// Shared by the fridge and the shopping list; each picks its own fallback
// for a name nothing matches.
const EMOJI: [string[], string][] = [
  [["canned", "tinned", "dåse", "beans", "bønner", "chickpea"], "🥫"],
  [["black pepper", "sort peber", "salt"], "🧂"],
  [["milk", "mælk"], "🥛"],
  [["butter", "smør"], "🧈"],
  [["egg", "æg"], "🥚"],
  [["yoghurt", "yogurt", "skyr"], "🥣"],
  [["cheese", "cheddar", "ost", "parmesan", "mozzarella", "feta"], "🧀"],
  [["cream", "fløde"], "🍶"],
  [["chicken", "kylling"], "🍗"],
  [["bacon"], "🥓"],
  [["ham", "skinke", "pålæg"], "🍖"],
  [["beef", "pork", "okse", "svin", "steak", "meat", "kød", "minced", "hakket"], "🥩"],
  [["salmon", "laks", "fish", "fisk", "tuna", "tun", "cod", "torsk"], "🐟"],
  [["shrimp", "prawn", "rejer"], "🦐"],
  [["sweet potato", "sød kartoffel"], "🍠"],
  [["potato", "kartof"], "🥔"],
  [["tomato", "tomat"], "🍅"],
  [["cucumber", "agurk"], "🥒"],
  [["lettuce", "salad", "salat", "spinach", "spinat", "cabbage", "kål"], "🥬"],
  [["pepper", "peber", "chili"], "🫑"],
  [["carrot", "gulerod", "gulerød"], "🥕"],
  [["broccoli"], "🥦"],
  [["mushroom", "svamp", "champignon"], "🍄"],
  [["leek", "porre", "spring onion", "forårsløg"], "🧅"],
  [["garlic", "hvidløg"], "🧄"],
  [["onion", "løg"], "🧅"],
  [["corn", "majs"], "🌽"],
  [["avocado"], "🥑"],
  [["herb", "basil", "persille", "parsley", "dild", "urter"], "🌿"],
  [["lemon", "lime", "citron"], "🍋"],
  [["apple", "æble"], "🍎"],
  [["banana", "banan"], "🍌"],
  [["berr", "bær", "strawberr", "jordbær"], "🍓"],
  [["orange", "appelsin"], "🍊"],
  [["grape", "vindrue"], "🍇"],
  [["bread", "brød", "rugbrød", "toast"], "🍞"],
  [["leftover", "rester"], "🍲"],
  [["juice"], "🧃"],
  [["oil", "olie"], "🫒"],
  [["flour", "mel"], "🌾"],
  [["sugar", "sukker", "honey", "honning"], "🍯"],
  [["rice", "ris"], "🍚"],
  [["pasta", "spaghetti", "noodle", "nudler"], "🍝"],
  [["oat", "havre", "cereal", "müsli"], "🥣"],
  [["stock", "bouillon", "fond"], "🍲"],
  [["soy", "soja", "vinegar", "eddike", "sauce", "sovs", "ketchup", "mustard", "sennep"], "🍶"],
  [["spice", "krydder", "cumin", "paprika", "curry", "cinnamon", "kanel"], "🌶️"],
  [["baking", "bagepulver", "yeast", "gær"], "🧁"],
  [["coffee", "kaffe"], "☕"],
  [["tea", "te"], "🍵"],
  [["nut", "nød", "mandel", "almond"], "🥜"],
  [["chocolate", "chokolade"], "🍫"],
];

export function foodEmoji(name: string): string | null {
  const lower = name.toLowerCase();
  // Short keywords ("te", "ris", "egg") only match the start of a word, so
  // "Eggs" is an egg but "Tomatoes" isn't tea.
  const words = lower.split(/[^\p{L}]+/u);
  for (const [keys, emoji] of EMOJI) {
    if (keys.some((k) => (k.length <= 3 ? words.some((w) => w.startsWith(k)) : lower.includes(k)))) {
      return emoji;
    }
  }
  return null;
}
