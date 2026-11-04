# Settings

The Settings page holds the values the plan keeps out of code, so a manager can change them without a code change.
This page says what each value is, where its starting value comes from, and which starting values are assumptions.

Only a manager can open the page at `/app/settings` or call its routes, and staff get a 403 from every one of them.
Each section is one row of the `settings` table, described in [database.md](database.md#settings).

## What reads each section

| Section | Read by | Starting value |
| --- | --- | --- |
| Worth listing | The worth-listing rule, step 9 of the [pricing pipeline](architecture.md#pricing-pipeline) | $30, the value the pipeline used before |
| Channel A fees | The net after fees beside the worth-listing rule, and Channel A's net on the approval page | 13.6% plus $0.40 per order, and $1.50 for supplies, the values the pipeline used before |
| Channel B fees | Channel B's net on the approval page | 20% from $15 and a flat $2.95 below that, and $1.50 for supplies, see below |
| Ask-to-sale factor | The price range, step 7 of the pricing pipeline | 0.645 for apparel and 0.94 for games and hardware, the values the pipeline used before |
| Seasonal calendar | The channel timing hint, which is [#20](https://github.com/KyleNaluan/blessings-abound/issues/20) and not built yet | Written for this page, see below |
| Box sizes | The box size dropdown in the package step on the approval page, from [#42](https://github.com/KyleNaluan/blessings-abound/issues/42), and the order of the pick list | Written for this page, see below |
| Shipping weight rules | The package weight check on the approval page, and every saved box size, which has to fit under the size limit | USPS Ground Advantage's published rules |

The pricing values start from the numbers the pipeline was tuned with, so nothing about the price changes until a manager changes them.
The evaluation in [evaluation.md](evaluation.md) always scores the values in code, and it ignores any change saved on this page.

## Routes

| Route | What it does |
| --- | --- |
| `GET /settings` | Every section, with who changed it last and when |
| `PUT /settings/worth-listing` | Replaces the worth-listing price |
| `PUT /settings/fees` | Replaces the Channel A fees |
| `PUT /settings/channel-b-fees` | Replaces the Channel B fees |
| `PUT /settings/ask-to-sale` | Replaces both ask-to-sale factors |
| `PUT /settings/seasonal-calendar` | Replaces the whole seasonal calendar |
| `PUT /settings/box-sizes` | Replaces the whole box size list |
| `PUT /settings/shipping-weight` | Replaces the shipping weight rules |
| `GET /settings/box-sizes` | The box sizes as the package step's dropdown shows them, each with the code it adds to the SKU |
| `GET /settings/seasonal-calendar` | The seasonal calendar, for the timing hint in #20 |

A save sends the whole section and the `updated_at` it was read with.
When another manager saved the section in between, the save gets a 409 and changes nothing, so one manager can't quietly undo another's change.
A save with a value the checks refuse gets a 422 with a sentence saying what to fix, and changes nothing.
A save that leaves out a field is refused rather than filled in with a default.

## Channel B fees

Channel B charges a flat fee on a small sale and a share of the price on a larger one, and the buyer pays for the shipping label.
The starting values are Poshmark's published US fees, quoted from Vendoo's [guide to Poshmark's selling fees](https://blog.vendoo.co/everything-you-need-to-know-about-poshmark-selling-fees), last updated on 2026-02-25:

- "For items sold under $15, Poshmark fees are a flat rate of $2.95."
- "The Poshmark selling fee is 20% of the sale price."
- On whether the seller ships: "Yes, but the buyer pays the shipping cost."

In plain words, a $12 sale leaves $9.05 before supplies, a $40 sale leaves $32, and the label costs the store nothing.
The net on the approval page takes the fee and the supplies off the listing price, and leaves the label out.

These choices are assumptions, labeled so the store can correct them:

- The values come from a third-party guide, because Poshmark's own help page needs a browser to load, and the guide quotes the same two tiers as every other guide we found.
- Channel B is Poshmark-style rather than Depop-style, see the [requirements](requirements.md), so a store that means Depop should change the fee rate and the flat fee.
- The supplies are the same $1.50 as Channel A's, on the guess that the store packs both channels' orders with the same mailers and boxes.

## Seasonal calendar

Each season is a kind of item, the words on an item card that mark an item as that kind, and the months it is worth listing in.
In the other months, an item of that kind is held for its season.
An item matches a season when its card has one of the season's words, the first season that matches is the one used, and an item that matches no season can be listed in any month.
That is why the narrower seasons come first, so a holiday sweater is read as a holiday sweater and not as any sweater.

The calendar was written for a store in Kansas City.
Each season's months start about a month before the peak a published resale guide gives, because that guide says to list seasonal items 2 to 4 weeks before peak demand, and they end when the guide says demand ends.

| Season | Words | Months | Why |
| --- | --- | --- | --- |
| Halloween costumes | costume, halloween | August to October | Demand starts in September and peaks from October 1 to 25, and prices drop after October 25 |
| Holiday sweaters | christmas, ugly sweater, holiday | October to December | Winter clothing peaks in November and runs through December, and holiday gifts should be listed by November 1 |
| Football gear | football, nfl, chiefs | August to January | Football season drives team merchandise from September, and the season runs into January |
| Coats and jackets | coat, jacket, parka, puffer, peacoat, overcoat | August to January | Heavy coats start selling in mid-October in northern regions, and winter clothing peaks in November |
| Sweaters | sweater, cardigan, turtleneck, fleece | September to February | Fall fashion should be listed by late August, and sweaters peak in October |
| Boots | boot | September to January | Fall and winter boots sell from September through November |
| Swimwear | swimsuit, swim, bikini | March to July | Beach and pool items sell in June, and summer clothing peaks in July |
| Shorts | shorts | March to August | Summer clothing peaks in July, and clearance starts in August |
| Sandals | sandal, flip flop | March to July | Summer clothing peaks in July |

The demand months come from Underpriced's [seasonal reselling calendar guide](https://www.underpriced.app/blog/seasonal-reselling-calendar-guide), which also gives the 2 to 4 week lead time.
The local weather backs up the cold and warm months.
The National Weather Service's 1991-2020 normals for Kansas City give a normal high of 74°F on October 1 falling to 61°F on October 31, [October normals](https://www.weather.gov/eax/kcrecnorm-oct), and 49°F on March 1 rising to 61°F on March 31, [March normals](https://www.weather.gov/eax/kcrecnorm-mar).
In plain words, coats are needed from late October and the weather turns warm through March, which is when the summer seasons start.

These choices are assumptions, labeled so the store can correct them:

- The months are our reading of the guide, which gives peaks and not a calendar, and Underpriced's own [listing calendar tool](https://www.underpriced.app/tools/best-time-to-list-calendar) says "There is no universal month for every item, platform, and region."
- The guide doesn't cover holiday sweaters or sandals, so those months follow its nearest guidance, winter clothing and the July summer peak.
- The guide gives September for football gear with no end, and the months to January follow the NFL season and the Chiefs, Kansas City's team, which is an assumption about this store's buyers.
- Every season is apparel, and games and hardware have none, because the guide's timing for them is about holiday gift buying rather than an item being out of season, so they can be listed in any month.

## Box sizes

Each size is one a store can stock, and it is written the way it goes on the SKU, after a space, such as `RT10272601 12x12x6`.
A box is written length by width by height, with the longer side of the opening first, so the same box is always written the same way, and the page refuses an 8x10x4 with a message to write it as 10x8x4.
A mailer is flat, so it is written width by length with no height.
Every side is measured to the nearest quarter inch, every box has to fit under the shipping size limit, and the list has to keep at least one box.

| Code | Kind | Source |
| --- | --- | --- |
| 10x13 | Mailer | A stock poly mailer size in Underpriced's [poly mailer size guide](https://www.underpriced.app/tools/poly-mailer-size-guide) |
| 12x15.5 | Mailer | The same guide, which uses it as its starting size |
| 14.5x19 | Mailer | The same guide |
| 8x6x4 | Box | Uline [S-4080](https://www.uline.com/Product/Detail/S-4080/Corrugated-Boxes-200-Test/8-x-6-x-4-Corrugated-Boxes), a stock 200 lb test box |
| 10x8x6 | Box | Uline [S-4103](https://www.uline.com/Product/Detail/S-4103/Corrugated-Boxes-200-Test/10-x-8-x-6-Corrugated-Boxes) |
| 12x12x6 | Box | Uline [S-4932](https://www.uline.com/Product/Detail/S-4932/Corrugated-Boxes-200-Test/12-x-12-x-6-White-Corrugated-Boxes) |
| 16x12x8 | Box | Uline [S-4235](https://www.uline.com/Product/Detail/S-4235/Corrugated-Boxes-200-Test/16-x-12-x-8-Corrugated-Boxes) |

The approval page offers these sizes in this order, and the pick list groups sold items by box in the same order, so a manager can put the list in the order the boxes sit in the store.
The pick of seven sizes is an assumption.
The mailers cover folded clothing from a shirt up to a coat, and the boxes run from a game case up to a console, but the store's real stock of boxes should replace this list.

## Shipping weight rules

The starting values are USPS Ground Advantage's rules, quoted from the [USPS Ground Advantage page](https://www.usps.com/ship/ground-advantage.htm):

- The price tiers under a pound are "up to 4 oz; up to 8 oz; up to 12 oz; and up to 15.999 oz", so a weight rounds up to the next tier, and past the last one to the next pound.
- "Maximum weight is 70 lbs.", which the page stores as 1120 oz.
- "Maximum combined length and girth (girth is the distance around the thickest part) is 130 inches."
- A package over 1,728 cubic inches pays a size-based weight of length times width times height divided by 139 when that is more than its real weight.

In plain words, a box is weighed by its size once it is bigger than 1 cubic foot, so a large light box costs what a heavier one would.
