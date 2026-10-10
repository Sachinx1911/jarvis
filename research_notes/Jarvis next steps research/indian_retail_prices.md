# Getting current Indian retail prices, specs and availability for a personal AI agent (October 2026)

Scope: Amazon.in, Flipkart, Croma, Reliance Digital, and brand India stores (Dell, HP, Lenovo, Apple India). Jarvis is a one-user, non-commercial Python assistant running on a laptop in India. Its research agents fail because a plain HTTP fetch returns menus and filters but no prices.
Research date: 2026-10-10. About 20 search and fetch calls were made. amazon.in pages (Conditions of Use) returned HTTP 503 to the fetch tool, so the Amazon ToS wording below comes from secondary copies.

## 1. Official APIs (Amazon Creators API / PA-API 5, Flipkart Affiliate API, others)

### Takeaway
PA-API 5 is deprecated and calls to it now return 403. Its successor, the Amazon Creators API, supports India (amazon.in). Access needs an approved Associates account plus at least 10 qualifying referral sales in the past 30 days, which a non-commercial personal assistant will almost never meet. The Flipkart Affiliate API still has documentation with rich price, stock and spec fields, but it is labelled "beta" and the docs look old, so whether it works today has to be confirmed by logging in. I found no public APIs for Croma, Reliance Digital, or the Dell/HP/Lenovo/Apple India stores.

### Cited Findings
- Amazon's official notice: "The Amazon Product Advertising API 5.0 (PA-API 5) has been deprecated and is being replaced by the Creators API". Applications still calling PA-API 5 get HTTP 403 `AccessDeniedException` — [Amazon Creators API: PA-API 5 deprecation](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/paapiv5-deprecation)
- Sources disagree on the cutoff date. A legacy PA-API page says "PA-API will be deprecated on April 30th, 2026" ([PA-API api-rates page, amazon.ca](https://webservices.amazon.ca/paapi5/documentation/troubleshooting/api-rates.html)). A WordPress plugin says migration was required by January 30/31, 2026 ([Affiliate Amazon Shortcode plugin](https://wordpress.org/plugins/affiliate-amazon-shortcode/)). Either way, it is retired as of October 2026.
- Creators API authentication: "CreatorsAPI uses secure authentication with OAuth 2.0 client credentials flow". Credentials "work globally across all marketplaces", but you need "a valid Partner Tag for the target marketplace and Creators API access approved in that region". GetItems takes up to 10 item IDs per call — [Creators API FAQ](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/frequently-asked-questions)
- India (https://www.amazon.in) is listed as a supported locale — [Creators API locale reference](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/locale-reference)
- Eligibility: Amazon's Japan Creators API page says you must "have at least 10 qualifying sales within the past 30 days" ([affiliate.amazon.co.jp/creatorsapi](https://affiliate.amazon.co.jp/creatorsapi)). Amazon's API-rates page says an account loses access if it has no qualified referring sales for 30 consecutive days, that access comes back about two days after referred sales ship, and that over-limit or revoked calls return 429 TooManyRequests ([Creators API api-rates, JP](https://affiliate.amazon.co.jp/creatorsapi/docs/en-us/concepts/api-rates)). Third-party guides report the same 10-sale rule ([AffiliateX](https://affiliatexblocks.com/docs/amazon-creators-api/)).
- Prices come from `OffersV2`. The legacy `Offers` resource is deprecated ("Offers is deprecated. Use OffersV2 instead") — [PA-API api-rates page](https://webservices.amazon.ca/paapi5/documentation/troubleshooting/api-rates.html)
- Rate limits are TPS/TPD per account. A batched GetItems with 10 ASINs counts as 1 transaction (legacy PA-API definition) — [PA-API api-rates](https://webservices.amazon.ca/paapi5/documentation/troubleshooting/api-rates.html). I did not find exact Creators API TPS/TPD figures for India.
- The Creators API has its own License Agreement and is bound by the Associates Operating Agreement and Program Policies (linked from the [deprecation page](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/paapiv5-deprecation): [license](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/license-agreement), [operating agreement](https://affiliate-program.amazon.com/help/operating/agreement/)). I did not read the caching and price-display clauses (see Gaps).
- The Flipkart Affiliate API 1.0 docs list a Product API (Product Feed, Delta Feed, Top Selling, Search by Keywords, Search by Product ID, Feed Download), an Offers API (All offers, Deals of the Day) and a Report API — [Flipkart affiliate API index](https://affiliate.flipkart.com/api-docs/affiliate_index.html)
- Flipkart Product Feed v1.0 fields: `maximumRetailPrice`, `flipkartSellingPrice`, `flipkartSpecialPrice`, `discount`, `offers`, `inStock`, `isAvailable`, `codAvailable`, `productUrl`, `sellerName`, `keySpecs`, `detailedSpecs`, `specificationList`. Feed URLs "are valid for 10 hours only" — [Flipkart Product APIs reference](https://affiliate.flipkart.com/api-docs/af_prod_ref.html)
- Flipkart release notes deprecate the unversioned Product APIs in favour of versioned ones (v1.1.0) — [Flipkart release notes](https://affiliate.flipkart.com/api-docs/af_changelog.html). The tools page calls the APIs "currently in beta" — [Flipkart affiliate tools](https://affiliate.flipkart.com/tools/affiliate-tools-info). A third-party guide says the developer guide was last updated in July 2016 (possibly stale) — [IPWeb](https://ipwebai.com/what-is-flipkart-affiliate-api/). The same search summary reported a limit of 20 calls/second per affiliate and one active token per account, citing the [Flipkart API FAQ](https://affiliate.flipkart.com/api-docs/af_faq.html). I did not open that page myself.

### Inferences
- The Creators API is the only ToS-clean way to get structured amazon.in price and availability data, but Jarvis cannot rely on it. A personal, non-commercial user with no referral sales will lose access, or never get it. Treat it as optional: use it only if Sachin already runs an active Associates India account.
- Flipkart's affiliate API is the best official route for Flipkart, if Sachin's affiliate account is approved and the API still returns data. Test this by logging in before planning around it.
- Croma, Reliance Digital and the brand stores have no API, so their pages have to be read as normal web pages.

### Gaps
- Exact Creators API TPS/TPD for India, and the caching and price-display rules (PA-API used to require price data to be refreshed or shown with a timestamp, roughly within 24h). Not verified in the 2026 license text.
- Whether the 10-sale rule applies the same way in Associates India. I only found it in the Japan doc and third-party sources.
- Flipkart affiliate eligibility, and whether the API still serves data in 2026. No 2025–2026 announcement either way.
- No search results found for official Croma, Reliance Digital, Dell, HP, Lenovo or Apple India product APIs or feeds. This is an absence of evidence, not proof that none exist.

## 2. Search and extraction APIs (Tavily, Exa, Firecrawl, Jina, Bright Data, SerpAPI)

### Takeaway
Tavily Extract is cheap, has an `advanced` depth for JS-heavy pages, and a `query` parameter that keeps only the relevant chunks. It is the easiest thing to try first on retailer and brand pages. SerpAPI's Google Shopping API returns structured price and seller rows, but those are Google's data, not the retailer page itself. None of these vendors guarantees Amazon.in or Flipkart prices, so test them on Sachin's machine.

### Cited Findings
- Tavily credits: 1,000 free a month, no card. Search costs 1 credit (basic) or 2 (advanced). Extract is charged per 5 successful URLs, roughly 0.2 credit per URL basic and 0.4 advanced, and failed extractions are free. Pay-as-you-go is $0.008/credit — [Tavily API credits docs](https://docs.tavily.com/documentation/api-credits)
- Tavily says Extract handles JavaScript-rendered pages. `extract_depth=advanced` is meant for JS-heavy and dynamic pages and tables. `query` plus `chunks_per_source` (1–5) returns only the relevant chunks. Up to 20 URLs per call — [Tavily Extract tutorial](https://docs.tavily.com/examples/quick-tutorials/extract-api.md); [OpenClaw Tavily tool doc](https://docs.openclaw.ai/tools/tavily.md)
- Tavily docs make no mention of a "keyless" mode. The credits page only describes getting a free API key — [Tavily API credits](https://docs.tavily.com/documentation/api-credits)
- SerpAPI Google Shopping returns `shopping_results` with `price`, `extracted_price`, `source` (seller), `product_link`, `delivery`, rating and more. `gl` takes a country code, and India support is listed separately — [SerpAPI Google Shopping API](https://serpapi.com/google-shopping-api)
- SerpAPI pricing: free plan of 250 searches/month (50/hour). Starter is $25/month for 1,000 searches — [SerpAPI pricing](https://serpapi.com/pricing)
- General Amazon scraping reports: strong bot defences (IP rate limits, fingerprinting, CAPTCHA walls). Datacenter IPs get flagged quickly. JS-rendered price elements and frequently changing selectors — [webscraping.ai FAQ](https://webscraping.ai/faq/amazon-scraping/how-can-i-avoid-being-blocked-while-scraping-amazon); [HackerNoon 2026](https://hackernoon.com/i-tried-every-way-to-scrape-amazon-in-2026-here-is-what-actually-works?source=rss); [Massive blog](https://www.joinmassive.com/blog/amazon-price-scraping)

### Inferences
- Tavily runs from Tavily's own datacenter IPs, so Amazon.in and Flipkart pages may come back blocked or without prices. Croma, Reliance Digital and brand stores are more likely to work. Jarvis should check the extracted text for an INR price pattern (₹ / Rs.) and treat a missing price as a failure, not as "no price".
- Paid scraping and unblocking proxies (Bright Data, ScraperAPI, Crawlbase and similar) exist mainly to get past Amazon's and Flipkart's anti-bot systems. That conflicts with the ToS in section 3, so they should not be recommended for Jarvis.
- SerpAPI or Google Shopping is useful for discovery: it finds which sellers list the item and gives a candidate URL and approximate price. The final price should still be confirmed on the retailer page.

### Gaps
- Exa, Firecrawl, Jina Reader and Bright Data pricing, and whether they return amazon.in/flipkart prices, were not verified in this session (tool budget). Firecrawl may restrict some domains. Unconfirmed.
- Not confirmed that Google Shopping (`gl=in`) still returns Indian results via SerpAPI in 2026. The country list was not opened.
- No live test of Tavily Extract on an amazon.in or flipkart.com product URL was done.

## 3. Headless browser (Playwright) and the ToS position

### Takeaway
A real Chromium browser (Playwright) usually renders the price, but Amazon's and Flipkart's terms prohibit automated data gathering. Amazon's license excludes "any use of data mining, robots, or similar data gathering and extraction tools" and "any collection and use of any product listings, descriptions, or prices". Flipkart's terms bar "deep-link, page-scrape, robot, spider" or other automated access. Scripted Playwright fetching of these two sites is therefore against their ToS, not just a gray area, even for one user. Expect CAPTCHAs from repeated or headless access.

### Cited Findings
- Amazon Conditions of Use (general Amazon wording, which the India site appears to share; the amazon.in page returned 503 so I could not confirm it directly): a limited licence for "personal and non-commercial use". The licence does not include "any collection and use of any product listings, descriptions, or prices" or "any use of data mining, robots, or similar data gathering and extraction tools" — [ConductAtlas: Amazon CoU data-mining provision](https://conductatlas.com/platform/amazon/amazon-conditions-of-use/provision/CA-P-018441/prohibition-on-data-mining-and-scraping-tools/); [ConductAtlas: licence and access](https://conductatlas.com/platform/amazon/amazon-conditions-of-use/license-and-access-restrictions/)
- Flipkart (as quoted by a secondary site, terms last updated 20 Nov 2025): users may not use "deep-link, page-scrape, robot, spider or other automatic device, program, algorithm or methodology, or any similar or equivalent manual process" to access or copy the platform — [itechguides](https://www.itechguides.com/?p=863860). I did not read Flipkart's own page.
- Headless Selenium from a datacenter IP hit CAPTCHAs within the first few pages of Amazon. Localized prices need in-country IPs — [Massive blog](https://www.joinmassive.com/blog/amazon-price-scraping); [webscraping.ai](https://webscraping.ai/faq/amazon-scraping/what-is-the-rate-limit-for-making-requests-to-amazon-before-getting-blocked)

### Inferences
- Running from Sachin's own Indian home IP at very low volume probably renders fine and rarely triggers CAPTCHAs. This is inference: no primary source measured it. Even so, the Amazon and Flipkart terms ban it regardless of volume, so it should not be a built-in Jarvis feature.
- Allowed alternative: Jarvis opens the product page in Sachin's normal browser (or the user pastes or confirms the price). That keeps a human in the loop and is ordinary personal browsing.
- Croma, Reliance Digital and the brand stores were not checked for ToS wording. Read each site's terms and robots.txt before automating them.

### Gaps
- Direct amazon.in Conditions of Use text (fetch returned 503) and Flipkart's own Terms of Use page were not read.
- Croma, Reliance Digital, Dell/HP/Lenovo/Apple India terms on automated access were not checked.
- How enforceable these terms are under Indian law for personal, non-commercial use was not researched. Not legal advice.

## 4. Price-comparison aggregators (Smartprix, 91mobiles, PriceHistory, BuyHatke)

### Takeaway
No public developer APIs were found for Smartprix, 91mobiles, PriceHistory or BuyHatke. They are consumer sites whose data is itself scraped from retailers, and it can lag. They are useful for discovery and price history, not as the final source for a price.

### Cited Findings
- Smartprix describes a database of 1,50,000+ products compared across e-tailers, with no API mentioned — [Smartprix About](https://us.smartprix.com/about/smartprix). Its app offers 90-day price trends — [App Store](https://apps.apple.com/app/id1142915507)
- Only third-party scrapers exist for Smartprix (Apify actor, about $2/1,000 results) and 91mobiles — [Apify Smartprix scraper](https://apify.com/stealth_mode/smartprix-product-search-scraper.md); [spider.cloud 91mobiles](https://spider.cloud/scrapers/91mobiles-com-scraper/)
- 91mobiles is described as offering real-time pricing and availability from major retailers, with no developer API found — [bitscale directory](https://bitscale.ai/directory/91mobiles)
- PriceCheckIndia offered a free publisher price-comparison API in 2012 (stale, likely defunct) — [YourStory 2012](https://yourstory.com/2012/05/free-to-use-price-comparison-apis-for-publishers-from-pricecheckindia/)

### Inferences
- Aggregator pages are mostly server-rendered spec and price lists, so a plain fetch or Tavily usually works. They are good for: (a) the list of retailers selling a model, (b) full specs, and (c) a sanity range for the price.

### Gaps
- No data on PriceHistory or BuyHatke APIs, or on how fresh aggregator prices are. Their terms on automated reading were not checked.

## 5. Practical recommendation for Jarvis

### Takeaway
Use a layered pipeline. Discovery comes from search, aggregators and SerpAPI Google Shopping. Price confirmation comes from official APIs where they are available (Flipkart affiliate if approved, Amazon Creators API only if eligible), Tavily Extract on Croma, Reliance Digital and brand-store pages, and a human-in-the-loop check for Amazon.in and Flipkart. The verifier should rate sources by tier instead of rejecting everything that is not a retailer page.

### Cited Findings
- Supporting facts are in sections 1–4: Creators API eligibility ([JP doc](https://affiliate.amazon.co.jp/creatorsapi)), Flipkart feed fields ([reference](https://affiliate.flipkart.com/api-docs/af_prod_ref.html)), Tavily cost ([credits](https://docs.tavily.com/documentation/api-credits)), SerpAPI free tier ([pricing](https://serpapi.com/pricing)), and the Amazon/Flipkart anti-robot clauses ([ConductAtlas](https://conductatlas.com/platform/amazon/amazon-conditions-of-use/provision/CA-P-018441/prohibition-on-data-mining-and-scraping-tools/); [itechguides](https://www.itechguides.com/?p=863860)).

### Inferences
- Suggested source tiers for the verifier:
  - Tier A (accepted as the price): official API response (Creators API OffersV2, Flipkart affiliate feed), or the retailer or brand page itself (Croma, Reliance Digital, dell.com/in, hp.com/in, lenovo.com/in, apple.com/in) fetched and showing an INR price. Store the source URL and fetch timestamp.
  - Tier B (indicative, must be labelled): Google Shopping via SerpAPI, Smartprix, 91mobiles. Show as "approx. ₹X via Smartprix, checked <time>", never as the confirmed retailer price.
  - Tier C (reject for price): blogs, news, LLM memory.
- For Amazon.in and Flipkart without API access, Jarvis gives the product URL plus the Tier B estimate and asks Sachin to confirm. No automated scraping.
- All prices are time-stamped with a short validity (for example, same day), because Indian e-commerce prices change during sales.
- Specs: brand spec pages, then aggregators, are reliable and usually server-rendered, so a plain fetch or Tavily often works.
- The verifier should check that an extracted page actually contains a ₹ amount near the product title. That catches the "menus/filters only" failure.
- Budget: Tavily's free 1,000 credits (about 2,500 basic extracts) plus SerpAPI's free 250 searches should cover one user's monthly product research.

### Gaps
- No live end-to-end test was run. Next step: try Tavily Extract (basic, then advanced) and SerpAPI `google_shopping` with `gl=in` on 3–5 real product URLs and measure the hit rate before building.
