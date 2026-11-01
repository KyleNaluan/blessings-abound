# SerpApi eBay search check

This is the answer to [#4](https://github.com/KyleNaluan/blessings-abound/issues/4): does SerpApi's eBay search return usable current prices for apparel and electronics?
Short answer: yes, for both, with two conditions.
The search needs the right condition ids for each category, and code has to filter titles for bundles, parts and variants before it takes percentiles.

## What was run

11 searches were spent of the 250 a month, 10 planned and 1 follow-up after the video game result.
All used `engine=ebay`, `buying_format=BIN`, `ebay_domain=ebay.com`, `_ipg=60` and the used condition filter `LH_ItemCondition=3000`, except the follow-up.
Each response is saved unchanged except for two removals, `api_key` and the `seller` object, because the seller's username is a personal detail the repo keeps out of fixtures.
The `json_endpoint`, `markdown_endpoint` and `raw_html_file` archive URLs under `search_metadata` were also removed, because they link to SerpApi's stored copy of the unredacted original and would otherwise let anyone recover the removed `seller` usernames.
They are in `api/tests/fixtures/serpapi/`, one file per query, named by the slug in the first column below.
Sold and completed listings are no longer supported by the engine, so every price is an asking price.

## Results per query

Prices are `price.extracted` in dollars, and "spread" is the 25th, 50th and 75th percentile of the 60 results in the response.
"Total" is `search_information.total_results`.
"Noise" counts results I judged not to be the item itself, read from the titles.

| Fixture | Total | Min to max | 25th / median / 75th | Noise in 60 | What the noise was |
| --- | --- | --- | --- | --- | --- |
| `levis-501-jeans` | 130000 | 5.50 to 79.99 | 23.77 / 29.00 / 35.99 | 0 | Nothing off-type, a few vintage "501XX" pairs at $54 to $80 |
| `nike-air-max-90` | 20000 | 20 to 300 | 45 / 80 / 109 | 0 | No accessories, but collabs and premium colorways run to $300, so the spread is wide |
| `patagonia-better-sweater` | 20000 | 20 to 89.98 | 29.99 / 39.95 / 45.99 | 6 | 5 fleece vests and 1 women's jacket |
| `carhartt-detroit-jacket` | 9200 | 100 to 715.61 | 165 / 227.50 / 299.99 | 0 | Vintage blanket-lined models (J97, J01) sell far above the modern jacket, so one query mixes two price levels |
| `lululemon-align-leggings` | 22000 | 8 to 65 | 19.99 / 28.49 / 35 | 0 | Flared, capri and ribbed variants only |
| `airpods-pro` | 10000 | 7.49 to 179.28 | 45 / 60 / 85 | 9 | 7 single replacement earbuds and 2 charging cases alone, and generations 1, 2 and 3 are mixed |
| `mario-kart-8-switch` | 110 | 37.09 to 449 | 195 / 250 / 300 | 57 | Almost all console bundles, only 3 of 60 are the game, see below |
| `mario-kart-8-switch-game-conditions` | 1200 | 28 to 45 | 31.50 / 34.99 / 38.99 | 1 | One multi-game lot with a price range and no single price |
| `ps4-slim-console` | 5600 | 85 to 200 | 109.99 / 123 / 144.95 | about 18 | Bundles with games, a headset or a second controller, but the median is $120 without them against $123 with them |
| `nintendo-switch-console` | 17000 | 69 to 379.99 | 115 / 129.99 / 150 | about 25 | Bundles with games or accessories, Lite models, and tablet-only listings with no Joy-Cons |
| `ring-video-doorbell` | 1800 | 5 to 109 | 19.99 / 25 / 31.99 | 3 | A lot of 6, a Spotlight Cam bundle and one listing whose title is a pasted description |

Two things stand out.
Accessory noise is a real problem only for electronics and games, and it is close to zero for apparel.
The spread is tight for most items, with the 75th over the 25th percentile between 1.24 and 1.89, and it is wide only where one query covers several models, which is Nike (2.42).

## The condition filter

`LH_ItemCondition=3000` held for every non-game query, since 59 or 60 of the 60 results in each carried the condition "Pre-Owned", and the exceptions are described below.
It does not hold for video games, because eBay uses different condition ids in the games categories.
With 3000, "Mario Kart 8 Deluxe Nintendo Switch" matched only 110 listings, and 57 of the 60 returned were consoles that include the game.
With `LH_ItemCondition=2750|4000|5000|6000` the same query matched 1200 listings and 59 of the 60 were the game itself, priced $28 to $45.
In those results eBay labels "Like New" as "New (Other)" (25 of 60) and the rest as "Pre-Owned" (35 of 60).

Two more limits on the condition field:

- The response gives one coarse label, "Pre-Owned", so staff's finer grade (Good, Very Good, Acceptable) can only be applied through the filter ids and never checked on the results.
- Two rows (one PS4, one Switch) carried the product name in `condition` instead of a grade, which looks like a grouped listing, so code should not assume the field is always a grade.

## Price quality

Apparel and electronics both return enough current listings to work with, because even the smallest pool (Ring, 1800) filled the page of 60.
The prices are asking prices, and 432 of the 600 results in the ten used-condition responses (72%) are marked "or Best Offer", so the real sale price is probably lower.
This is consistent with the ask-to-sale factor of 0.645 in [architecture.md](architecture.md), but this check cannot confirm the factor, because there are no sold prices to compare against.

Applying 0.645 to the median of each query, against the $30 yes rule:

| Item | Median ask | Median x 0.645 | Rule |
| --- | --- | --- | --- |
| Levi's 501 jeans | 29.00 | 18.71 | no |
| Nike Air Max 90 | 80.00 | 51.60 | yes |
| Patagonia Better Sweater | 39.95 | 25.77 | no |
| Carhartt Detroit jacket | 227.50 | 146.74 | yes |
| Lululemon Align leggings | 28.49 | 18.38 | no |
| AirPods Pro | 60.00 | 38.70 | yes |
| Mario Kart 8 Deluxe (game only) | 34.99 | 22.57 | no |
| PS4 Slim | 123.00 | 79.34 | yes |
| Nintendo Switch console | 129.99 | 83.84 | yes |
| Ring Video Doorbell | 25.00 | 16.13 | no |

These are medians of the raw 60 results, before any title filter, so they are only a rough guide.

## Other things in the responses

- About a quarter of each page (12 to 16 of 60) is `sponsored: true`.
  The prices look the same as the organic ones, so they can stay, but the flag lets code drop them if a duplicate shows up, and the same listing appears more than once in some responses (the Switch has one listing three times).
- 8 of 660 results carry `bids.time_left` while `buying_format` still says `buy_it_now`, which looks like a fixed-price listing with an end date, so the price is still a Buy It Now price.
- A listing with several variants gives `price.from` and `price.to` instead of `price.extracted`, which happened once in the Switch response and once in the Mario Kart lot, so code must handle a price with no `extracted`.
- `old_price` appears on discounted listings, and `price` is already the discounted price.

## Fields the comps code should use

| Field | Use |
| --- | --- |
| `organic_results[].product_id` | Stable id, to drop duplicates and to build the comp link |
| `organic_results[].title` | The title filter for accessories, lots, parts, bundles and wrong variants |
| `organic_results[].link` | The comp link shown to staff |
| `organic_results[].price.extracted` | The asking price, or `price.from` and `price.to` when it is missing |
| `organic_results[].shipping.extracted` | Kept for display, left out of the price percentiles |
| `organic_results[].condition` | Sanity check on the filter, not a grade |
| `organic_results[].buying_format` | Sanity check that the result is Buy It Now or Best Offer |
| `organic_results[].subtitle` | Size for apparel, such as "Size 30 in x 32 in", useful for matching staff's size |
| `organic_results[].epid` | eBay's catalog product id, present on 155 of 600 results, a strong match signal when it exists |
| `organic_results[].sponsored` | Flag, to drop duplicates of sponsored listings |
| `search_information.total_results` | How many listings matched, a signal for how well the query fits |
| `search_metadata.status` | Must be `Success` before the response is cached |

The comps code should ignore `thumbnail`, `serpapi_link`, `watchers`, `rating`, `reviews`, `location` and `returns`.
It should also leave `seller` out of anything it stores, since the fixtures here have had it removed.

## Verdict

Usable.
The 25th, 50th and 75th percentiles of asking price are stable for apparel straight from the response, and for electronics once the title filter removes bundles and parts.
The $30 yes rule depends on the ask-to-sale factor, and six of the ten items sit within about $15 of the cutoff, so the factor decides those, not the search.

What the comps work (#12, #14, #15) needs to take from this:

1. Use a different condition id list for the video games category (`2750|4000|5000|6000`) than for everything else (`3000`), or the game query returns consoles.
2. Run the title filter for electronics and games before the percentiles, because a bundle or a single earbud can sit anywhere in the range.
3. Treat the model and generation as part of the query, because Nike Air Max 90, Carhartt Detroit and AirPods Pro each cover several price levels.
4. Handle a price with `from` and `to` and no `extracted`.
5. Cache by the full parameter set, including the condition ids, since the same words with a different filter return a different pool.
