# Translation rules: repasovanyiphone.cz → Ukrainian (uk) and Russian (ru)

The site compares refurbished / second-hand iPhones sold by Czech shops. Readers: Ukrainian- and Russian-speaking people
**living in the Czech Republic** who shop in Czech e-shops and pay in Czech crowns. Translate from the Czech source directly into
each language; Ukrainian is never a conversion of the Russian text.

## Language
- **Ukrainian:** modern standard literary Ukrainian, natural and fluent, as a native editor would write it. No Surzhyk, no Russianisms
  (e.g. «відновлений», not «відновлюваний»; «вживаний», not «б/в» in running text; «знижка», «промокод», «кошик»; «оновлення», not «апдейт»).
  Address the reader as «ви» (lowercase).
- **Russian:** natural modern Russian, address the reader as «вы» (lowercase).
- Short, clear sentences like the Czech original. Translate the meaning, not word by word. Keep the tone (practical, calm, no marketing hype).
- Quotation marks: «…». Dash: – or — as in the source.
- **Never invent or add facts**, numbers or claims. Do not drop information.

## Placeholders (machine-checked, a mismatch throws the translation away)
- `{0}`, `{1}`… are numbers (prices, years, GB, percent, dates). Keep every one; you may reorder them and repeat them; never add a new index.
- `<1>…</1>`, `<2/>`… are HTML tags around words (links, bold). Keep **every** placeholder exactly once, with the matching closing one,
  around the corresponding words. You may move them within the sentence.
- Some keys contain real HTML (`<b>…</b>`, `<span class="hand">…</span>`, `<code></code>`): keep those tags and attributes verbatim.
- A key with `|` (e.g. `nabídka|nabídky|nabídek`) is a plural set: give three forms one|few|many of the target language
  (uk: пропозиція|пропозиції|пропозицій; ru: предложение|предложения|предложений).
- Leading/trailing punctuation and spaces of the key (e.g. `, od {0}`, ` · zkuste jiný filtr`) must stay at the same place.

## Never translate
iPhone and model names (iPhone 15 Pro Max, iPhone SE (2022), iPhone Air, mini, Plus, Pro, Max), iOS, Apple, Apple Intelligence,
Face ID, Touch ID, USB-C, Lightning, eSIM, SIM (as a word: SIM-картка / SIM-карта), A+/A/B/C grades, GB/TB, Kč,
shop and company names (MobileGear, JabkoLevně, Smarty, iPhoneMarket, Aukro, iSTYLE, Allegro, Swappie, Refurbed, Vodafone, Home Credit,
eHub, CJ, Google, Seznam, Bazoš, Sbazar), URLs, e-mail addresses, Czech names of Czech institutions when they are a proper name
(keep them and explain in the target language the first time if the sentence needs it: e.g. «Česká obchodní inspekce (Чеська торговельна інспекція)»).
Prices stay in **Kč** (not «крон» after a number; the word «крона» is fine in running text).

## Terms (uk / ru)
| Czech | Ukrainian | Russian |
|---|---|---|
| repasovaný iPhone | відновлений iPhone | восстановленный iPhone |
| repas, repasy | відновлені iPhone / відновлення | восстановленные iPhone / восстановление |
| použitý, z druhé ruky | вживаний, з рук | б/у, подержанный |
| bazar, bazarový (iPhone z bazaru) | вживаний iPhone з оголошень / «з рук»; в заголовках: б/у | б/у с рук / с объявлений; в заголовках: б/у |
| zánovní | як новий (майже новий) | как новый (почти новый) |
| rozbalený | розпакований | распакованный |
| nový | новий | новый |
| stav, kvalita A+/A/B/C | стан A+/A/B/C | состояние A+/A/B/C |
| slevový kód | промокод | промокод |
| sleva | знижка | скидка |
| košík | кошик | корзина |
| obchod, e-shop | магазин, інтернет-магазин | магазин, интернет-магазин |
| nabídka | пропозиція | предложение |
| záruka | гарантія | гарантия |
| reklamace | рекламація (претензія) | рекламация (претензия) |
| kondice / kapacita baterie | стан (ємність) акумулятора | состояние (ёмкость) аккумулятора |
| výměna baterie | заміна акумулятора | замена аккумулятора |
| výkup | викуп | выкуп |
| na splátky | у розстрочку | в рассрочку |
| půjčka | позика (кредит) | заём (кредит) |
| paměť (128 GB) | пам'ять | память |
| barva | колір | цвет |
| srovnání | порівняння | сравнение |
| průvodce (sekce) | Гід (Гід покупця) | Гид (Гид покупателя) |
| vývoj cen | динаміка цін | динамика цен |
| podpora iOS | підтримка iOS | поддержка iOS |
| tarif, operátor | тариф, оператор | тариф, оператор |
| doprava | доставка | доставка |
| s DPH | з ПДВ | с НДС |
| IČO | IČO (ідентифікаційний номер компанії) | IČO (идентификационный номер компании) |
| spotřebitel | споживач | потребитель |
| občanský zákoník | Цивільний кодекс ЧР | Гражданский кодекс ЧР |

Apple colour names: translate naturally (černá → чорний / черный, bílá → білий / белый, přírodní titan → натуральний титан / натуральный титан,
vesmírně černá → чорний космос / черный космос, vesmírně šedá → сірий космос / серый космос, temně inkoustová → темне чорнило / темные чернила,
(PRODUCT)RED → (PRODUCT)RED). Colour names stand alone in the UI, use the masculine form in Ukrainian/Russian (it agrees with «колір/цвет», «iPhone»).

Dates: «27. listopadu 2026» → «27 листопада 2026» / «27 ноября 2026» (keep the placeholders: `{0}. listopadu {1}` → `{0} листопада {1}` / `{0} ноября {1}`).

## SEO (only where it fits)
People write Cyrillic searches like «айфон 15 про макс б/у», «айфон 13 б/у цена», «восстановленный айфон».
- In **page titles and the main heading (H1) of model pages** (keys like «Repasovaný a použitý iPhone {0} Pro Max», «iPhone {0} Pro: cena, bazar a repasovaný od {1} Kč»):
  keep «iPhone …» and add the Cyrillic search form once, e.g.
  uk: «iPhone {0} Pro Max (айфон {0} про макс) б/у і відновлений від {1} Kč»,
  ru: «iPhone {0} Pro Max (айфон {0} про макс) б/у и восстановленный от {1} Kč».
  Elsewhere keep just «iPhone …».
- Keep titles short (≈ 65 characters when possible).

## Site rules (also in translation)
- Never state how many shops the site compares (if the Czech text lists shop names, keep the list, but never add a count).
- Do not put Home Credit next to claims about loan quality.
- Privacy page: keep the operator data exactly (name, address, IČO, e-mail).
