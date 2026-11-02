# Vision accuracy

This page measures reading the item, and [evaluation.md](evaluation.md) measures pricing.

**Not scored yet.** The labels and this rule were committed before the first score, which `git log -- api/eval/vision_labels.json` shows.

## How it is matched

Accuracy is the share of cards marked correct, and a near miss counts against it, so the headline number never gives partial credit.
Text is compared in lower case with accents and punctuation removed, on whole words.

- **Brand** reads only the card's `brand` field.
  It is correct when it contains an accepted name, which is the maker or publisher of the item, and any other name in the label's `brand_accepted`.
  It is a near miss when it contains a product line or series instead of the company, such as "PlayStation" for Sony, from `brand_near`.
  Any other name is wrong, and an empty field is missing.
- **Unknown-brand items** have a label of no brand.
  An empty field is then correct, and naming any brand is wrong, because a guessed brand would send the search the wrong way.
  This set has none of these items, so the rule is not exercised by the results here.
- **Category** reads the card's `category` field and must equal the label, with no near miss.
- **Product** reads the card's `product`, `exact_model` and `search_query` fields together, because the prompt keeps `product` plain and puts the name in the other two.
  It leaves out `platform` and `visible_text`, so a platform or a logo alone doesn't name the item.
  It is wrong when it contains a phrase from `product_wrong`, which names a different system or model from the same maker, even if a right phrase also appears.
  It is otherwise correct when every phrase of one `product_right` alternative appears.
  The product is the system, accessory or game title a buyer would name, so color, storage size, region and revisions such as Slim or Model 2 aren't required.
  Models sold under their own name are required, such as the Game Boy Color, the DS Lite and the 3DS XL.
  It is a near miss when it matches a `product_near` alternative, which is the right family or kind of thing without the specific product, such as a game cartridge with no title.
  Anything else is wrong, and the model can't leave this empty because `search_query` is required.

Labels come from the identity already recorded for each item in `api/eval/items.json` and `api/eval/fresh_items.json`, not from what the model read.
`labelled_by` says who wrote each label, and `checked_by` stays empty until a person has looked at the photo and label together.
