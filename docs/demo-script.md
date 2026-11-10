# Demo script

This is the script for showing Turnstone to the judges at Hack-A-Roo, on Friday, November 13, from 9 AM to 12 PM in MNLC 352.
The core run goes from a photo to a decision in under 3 minutes, and an optional extension shows the rest of the item's path for a judge who asks for more or for the 5-minute finalist talk.
The wording on screen is from the interface on `main` after the cleanup in pull request #90.

## Before judging

- Do the [wake checklist](../README.md#wake-checklist) the day before and again 15 minutes before judging starts.
- Have the offline demo built and running on the laptop, as the [Offline demo](../README.md#offline-demo) section describes, with the synthetic sales history loaded as [Resetting the demo data](#resetting-the-demo-data) shows.
- Download the backup video from the shared drive to the laptop's desktop, so it plays without a network.
- Open two browser windows on the laptop: a normal one signed in as `demo.staff` on the home page, and a private one signed in as `demo.manager`.
  Two windows are needed because one browser window holds only one sign-in, and signing out and in again costs about 15 seconds.
- Have the demo jeans, or their photo, ready to upload, and the jacket for the extension.
- Set the browser zoom so the price box and the list of eBay listings fit on screen together, so the judges don't have to wait for scrolling.

## Demo items

### Core run: Levi's 501 jeans, pre-owned

Use a real pair of Levi's 501 jeans if one is at hand, or the evaluation photo [Levi's 501 raw jeans.jpg](https://commons.wikimedia.org/wiki/File:Levi%27s_501_raw_jeans.jpg), which is CC BY-SA 2.0 by Michael Carian.
These jeans work in every rung of the [fallback ladder](#fallback-ladder), because the offline demo's stand-in answers every photo with the same Levi's 501 card, so the item on screen stays the same when the demo switches to the laptop.

On the hosted demo, the vision model reads the photo and the price comes from live eBay listings, so the numbers move a little from day to day.
In the [pricing evaluation](evaluation.md), the model read this photo as "Levi's vintage blue jeans" and the pipeline priced it at $16.48 to $33.86 with a typical $24.19, which held the sold reference of $33.12 and came out as not worth listing.
On the offline demo, the numbers come from the saved eBay response and are always the same:

| Shown | Offline value |
| --- | --- |
| Low, typical, high | $16.12, $19.34, $24.16 |
| Left after eBay fees and supplies | $14.81 |
| Listings the price comes from | 54, after 5 far from the rest were left out of 59 |
| Recommendation | Not worth listing, high confidence, because $14.81 is under the $30.00 bar |

A no is the point of the core run, because it shows the app saving staff from photographing, listing and shelving an item that would clear less than the store's $30 bar.

### Extension: a Carhartt jacket

The extension needs an item worth listing, and a branded jacket goes on both mock channels, because Channel B takes clothing only.

- **Hosted:** use a real Carhartt jacket, or the evaluation photo [Carhartt.jpg](https://commons.wikimedia.org/wiki/File:Carhartt.jpg), a Carhartt Active hooded jacket, which is CC BY 4.0 by Isaac Barbosa.
  In the evaluation, the model read it as a "Carhartt black hooded canvas active jacket" and the pipeline said worth listing, at $43.84 to $64.49 with a typical $53.91.
  That range was under the approximate sold reference of $88.04, so the app underpriced this one.
  The hosted extension was checked end to end on 2026-11-09 with [Carhartt Hooded Jacket (9808828856).jpg](https://commons.wikimedia.org/wiki/File:Carhartt_Hooded_Jacket_(9808828856).jpg), a brown canvas hooded jacket, which is CC BY-SA 2.0 by Eli Duke.
  The model read it as a brown Carhartt canvas "hooded jacket", both drafts passed the claim check, and the pipeline said worth listing, at $57.81 to $80.62 with a typical $64.49.
- **Offline:** the stand-in always reads jeans, so edit the card before confirming it.
  Set Brand to `Carhartt`, Product to `Detroit jacket`, Color to `brown`, Material to `duck canvas` and Visible text to `Carhartt`, clear Exact model, and set Search to `Carhartt Detroit jacket`.
  Visible text and Exact model must change too, because the claim checker compares the draft with the card, and "Levi's 501" left there could let the stand-in's jeans listing through for a jacket.
  The saved response then gives $107.23 to $193.49 with a typical $145.12, $123.48 left after fees, and worth listing with high confidence.

Typing the offline card takes about 40 seconds, so for the finalist talk, take the jacket through to its "Yes, list it" before the talk starts and leave that tab open at "Where and when to list it".

### Resetting the demo data

On the laptop's offline demo, this clears every item, decision, listing and photo, and the API seeds `demo.staff` and `demo.manager` again when it starts:

```sh
docker compose -f docker-compose.yml -f docker-compose.offline.yml down -v
docker compose -f docker-compose.yml -f docker-compose.offline.yml up -d --wait
docker compose -f docker-compose.yml -f docker-compose.offline.yml exec api python -m app.synthetic_sales
```

The last command is the README's [synthetic sales history](../README.md#synthetic-sales-history) loader, run inside the API container so it needs no `uv` and no network.
With the images already built, the first two commands took 26 seconds, and the loader took about 2 seconds and printed "656 items, 369 listings and 106 sales".
The browser stays signed in through a reset, so reload the page afterwards.

The hosted demo has no reset, so its items and decisions pile up from one judge to the next.
From the second run on, taking the same jeans in again shows "This may have been rejected before", because the photo matches the jeans staff already said no to.
Press "Take it in anyway" and say "It remembers we already said no to these jeans, so nobody appraises the same item twice by accident."
The comps search for the same words is cached for 7 days, so repeat runs spend no SerpApi searches.

## Core run: photo to decision

Start signed in as `demo.staff` on the home page, "Welcome, demo.staff".
Each step gives what to click, what to say, a target time and the running total.

| Step | Target | Running total |
| --- | --- | --- |
| 1. The problem | 0:20 | 0:20 |
| 2. Intake | 0:25 | 0:45 |
| 3. The item card | 0:30 | 1:15 |
| 4. The price and the comps behind it | 0:45 | 2:00 |
| 5. The decision | 0:30 | 2:30 |
| 6. Close | 0:15 | 2:45 |

### 1. The problem (0:20, total 0:20)

Click nothing yet.

> Blessings Abound sends donated items to its online team, and someone has to decide whether each one is worth the time to photograph, price and list.
> Turnstone takes a photo and a few details, and in about a minute tells staff what the item is, what it would sell for, and whether it's worth listing.

### 2. Intake (0:25, total 0:45)

Click "Appraise an item", then "Take or choose a photo" and pick the jeans photo.
Under "Department it came from" pick "Clothing and shoes", under "Condition" pick "Pre-owned", and click "Take it in".

> Staff add up to four photos and the details the photo can't show, like condition and flaws.
> The item gets its SKU right away, so it's tracked from here on.

The heading changes to "Taken in as DS..." with the new SKU.

### 3. The item card (0:30, total 1:15)

Point at the "Item card" box: the model's confidence, Brand, Product, Color, Material and the Search line.
Click "Confirm and get the price".

> A vision model reads the photo into this card, and staff can fix any field before anything is searched.
> The search line is what we'll look up on eBay, so a wrong read gets caught here and not in the price.

### 4. The price and the comps behind it (0:45, total 2:00)

Point at Low, Typical and High, then "Left after eBay fees and supplies", then the eBay listings under "Searched eBay for".
Click "Show all 59 listings" if a judge leans in, which shows a different count on the hosted demo, and point at the line under the list, "The range is these asking prices times 0.645, because items sell for less than they're listed at."

> The price never comes from the language model.
> Code takes similar eBay listings, drops the ones far from the rest, and turns the asking prices into a likely sale price, and every listing it used is right here.
> Then it takes off eBay's fees and the shipping supplies, so staff see what the store would actually keep.

### 5. The decision (0:30, total 2:30)

Point at "Not worth listing, high confidence" and the sentence under it.
Read the number under "Left after eBay fees and supplies" off the card, because the hosted demo shows about $23 and the offline demo shows $14.81, and say that number in the first line below.
Click "No, don't list it", type `Worth too little online` under "Why it isn't being listed", pick "Back to the store floor", and click "Save the no".

> These jeans would leave about $23 after fees, and the store told us an item has to clear $30 to be worth listing online, so the app says no.
> Staff make the final call either way, and going against the recommendation asks for a reason, so a manager can see why.

The page says "Saved your decision: no. It goes back to the store floor." and the jeans show under "Recent decisions".

### 6. Close (0:15, total 2:45)

> That's one item from photo to decision in a couple of minutes, with the price explained and a person making the call.
> An item that is worth listing goes on to drafts, manager approval and two sales channels, and I can show that if you'd like.

### What was measured

On the offline demo, built from pull request #90, these were the waits after each click:

| Click | Wait |
| --- | --- |
| "Take it in" | 0.9 to 1.2 seconds |
| "Confirm and get the price" | 0.8 to 1.4 seconds |
| "Save the no" | under 1 second |

Clicking through the whole core run with no talking took 71 seconds, and a second run after a reset gave the same numbers and no duplicate photo warning, so the targets above are mostly speaking time.
The hosted demo's waits weren't measured for this script, and they are longer, because the vision model and SerpApi are real calls and Render's free service takes about a minute to wake if it has been idle.

## Extension: from yes to sold

Use this for a judge who asks for more, or in the 5-minute finalist talk.
The mock channels are hosted on Render next to the API, as the README's [Mock channels on Render](../README.md#mock-channels-on-render) says, so the whole extension runs on the hosted demo with the real vision model, and falls back to the offline demo like the core run.
Wake the channels with the README's [Wake checklist](../README.md#wake-checklist) first, because a sleeping channel takes about a minute to wake and the listing in E3 waits for it.
If time runs short, drop E5 first, then the talk in E2, and keep E3 and E4, because the sale taking the item off the other channel is what sets this app apart from a price lookup.

| Step | Target | Running total | Drop order |
| --- | --- | --- | --- |
| E1. A yes, with where and when to list it | 0:45, or 0:15 if staged | 0:45 | Stage it instead |
| E2. Drafts and the claim check | 0:30 | 1:15 | Second |
| E3. Manager approval and publish | 0:40 | 1:55 | Keep |
| E4. A sale on one channel ends the other | 0:30 | 2:25 | Keep |
| E5. A sales question | 0:25 | 2:50 | First |

For the 5-minute talk, the core run's 2:45 plus a staged E1 and E2 to E4 comes to about 4:40, and adding E5 runs over.

### E1. A yes, with where and when to list it (0:45, total 0:45)

Click "Appraise another item" and take the jacket in as in steps 2 and 3, editing the card offline as [Demo items](#extension-a-carhartt-jacket) says.
Click "Confirm and get the price", point at "Worth listing", and click "Yes, list it".
Point at "Where and when to list it", which on the offline demo says "Channel A and Channel B both take apparel, and its season, Coats and jackets, runs from August to January, so list it now."

> This jacket clears the bar easily, so it's a yes.
> The app checks which channels take it and the store's seasonal calendar, and says list it now on both.

### E2. Drafts and the claim check (0:30, total 1:15)

Leave both channels ticked and click "Write the listing".

> The model drafts a title and description for each channel, and code checks every claim in them against the card.

On the offline demo, both drafts say "The model's draft made claims the card doesn't support, so this is the fixed template." and "It said: levis, 501", because the stand-in always writes about the jeans.

> Here the draft talked about Levi's jeans for a Carhartt jacket, so the checker threw it out and used the fixed template instead.

On the hosted demo, a draft that passes shows no notice, so say only the first line.
Click "Send for manager approval", and the page says "Sent to a manager for approval."

### E3. Manager approval and publish (0:40, total 1:55)

Switch to the private window signed in as `demo.manager`, reload the home page, and click the "Approvals" card, which says "1 item to approve".
Click the jacket under "Waiting for approval".
Under "Package", type `48` in "Package weight (oz)", pick "14.5x19 mailer" under "Box size", click "Save the package", then click "Approve".
Under "Package and shelf", type `A3` in "Shelf or bin" and click "Save and store".

> A manager checks the listing and its price for each channel, enters the box and the shelf, and approves it.
> Storing it lists it on both channels.

Each channel's box changes to "Live on Channel A." and "Live on Channel B.", which took about 5 seconds offline and about 3 seconds on the hosted demo with both channels awake.

### E4. A sale on one channel ends the other (0:30, total 2:25)

Open Channel A's storefront in a new tab, at https://blessings-abound-channel-a.onrender.com on the hosted demo or http://localhost:8001 offline, and click "Buy now", leaving "Tell the seller right away, by sale webhook" ticked.
Open Channel B's storefront, at https://blessings-abound-channel-b.onrender.com or http://localhost:8002, or reload it if it's already open.

> Channel A and Channel B are mock shops we built, standing in for a marketplace and a clothing resale app.
> When it sells on one, the app takes it down from the other within seconds, so the store never sells the same jacket twice.

Channel B says "Nothing is for sale right now.", which happened about 1 second after the purchase, both offline and on the hosted demo.
If there's time, click "Pick list" in the manager window, which shows the jacket under "14.5x19 mailer · 1 item" with its shelf, A3.

### E5. A sales question (0:25, total 2:50)

In the manager window, click "Dashboards", type `Which month sells the most apparel?` under "Ask about sales", and click "Ask".

> Managers can ask about sales in plain words.
> The model only picks which tested function to run, and code computes the answer, which is shown under it.

Offline, it answered in about 3 seconds with September as the busiest month for apparel and November the quietest, and "Worked out with seasonality(category="apparel")" under it.
Point at the "Demo history" label and say the history is synthetic, because the store has no sales history we could use.

## Fallback ladder

Move down one rung at the first trigger, and don't try to fix anything in front of the judges.

| Rung | Where | Switch to the next rung when | Say when switching |
| --- | --- | --- | --- |
| 1. Hosted demo | https://blessings-abound.pages.dev on the laptop | Sign-in, "Take it in" or "Confirm and get the price" is still waiting after 20 seconds, the home page says "Can't reach the API", or any error shows | "The venue network is slow today, so I'll run the same app on this laptop with no network, where a stand-in answers for the model and eBay with saved responses." |
| 2. Offline demo | http://localhost:5173 on the laptop | The page doesn't load, the sign-in fails, or any error shows | "Rather than fix this now, here's a recording of the same run from earlier." |
| 3. Backup video | The file on the laptop's desktop, from the shared drive | It's the last rung, so if it won't play, talk the judges through the poster | Nothing more to switch to |

If the switch happens partway through the core run, start the offline run from step 2, because the item card and the price are the same jeans.

## Shot list for the backup recording

Record it on the hosted demo, so the judges see the real vision model and live eBay listings, and fall back to the offline demo only if the hosted demo is down on the day.
Record the browser window only, at the size used for judging, with no bookmarks bar or other tabs showing, and narrate the lines from the core run or add them as captions afterwards.
Aim for 2:30 to 2:45, and save it to the shared drive.

1. The home page, signed in as `demo.staff`, showing "Welcome, demo.staff". Hold 3 seconds.
2. Click "Appraise an item", and show the empty form.
3. Choose the jeans photo, and hold on the photo in the upload area for 2 seconds.
4. Pick "Clothing and shoes" and "Pre-owned", and click "Take it in".
5. Hold on "Taken in as DS..." with the SKU for 2 seconds.
6. Hold on the "Item card" for 5 seconds, moving the pointer over the model's confidence, Brand, Product and Search.
7. Click "Confirm and get the price", and hold on the price box for 5 seconds once it appears.
8. Move the pointer over Low, Typical, High and "Left after eBay fees and supplies".
9. Scroll to the eBay listings and hold 3 seconds, click "Show all 59 listings" (the number may differ on the hosted demo), and hold on the line about the 0.645 factor.
10. Hold on the recommendation and its sentence for 4 seconds.
11. Click "No, don't list it", type the reason, pick "Back to the store floor", and click "Save the no".
12. Hold on "Saved your decision: no." and the "Recent decisions" table for 3 seconds, and end.

If a second clip is wanted for the extension, record it on the hosted demo too, following E1 to E5 in order, as its own file.

## Likely judge questions

**Does the AI set the price?**
No, because the price comes from code over similar eBay listings, and the language model only reads the photo, drafts listing text and words explanations.
Anything it writes is checked by code, which throws out a draft that claims something the card doesn't say.

**How good are the prices?**
On 30 games and hardware items that had no part in tuning the rules, the price range held the real sale price for 21 of them, against 14 for a baseline of raw eBay asking prices, with a median error of 19.7% against 31.2%.
On 26 clothing items it's a tie at best, 12 in range against the baseline's 13, with a median error of 35.0% against 34.2%, so the app doesn't beat simply looking at eBay for clothing yet.
These are small samples, and [evaluation.md](evaluation.md) has every item and its limits.

**How well does it read photos?**
On 48 games and hardware photos, it got the brand right on 44, the category on all 48 and the product on 38.
Those are public Wikimedia Commons photos, not photos from a thrift store, and clothing isn't measured yet, which is why staff confirm the card before any search, as [vision-accuracy.md](vision-accuracy.md) says.

**Is it selling on real sites?**
No, Channel A and Channel B are mock shops we built for this project, so nothing is listed on a real marketplace.
The sales dashboards run on a synthetic history generated from published figures, because the store has no sales history we could use, and every chart says so.
