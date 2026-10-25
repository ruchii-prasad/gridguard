# GridGuard: 3-minute demo video script

**Setup:** open https://gridguard-microgrid.streamlit.app and load it once beforehand. Click each
scenario once so results are cached; the first load takes about 20 s. Record the screen with
**⌘⇧5 → Record Selected Portion** on a Mac, with the microphone on. Read at a calm pace. Each
block is roughly the time shown.

---

**0:00–0:20 · Problem** *(Overview tab, Normal operation)*
> "Solar-and-battery microgrids power campuses, clinics and villages. But most battery controllers
> follow fixed rules. They waste midday solar, empty the battery right before an outage, and leave
> no trustworthy record of what they did. GridGuard fixes all three."

**0:20–0:50 · What it does** *(point at the four numbers, then the battery chart)*
> "GridGuard is an optimizer. Every 15 minutes it schedules solar, the battery, the grid and two
> kinds of load: critical loads that must stay on, and flexible loads like water pumping that can
> move. We compare it against a strong rule-based controller, not a weak one. On a normal day it's
> 5 percent cheaper and ends the day with the battery at its target, while the rule-based
> controller drains it."

**0:50–1:30 · Resilience** *(select Grid outage → Dispatch tab)*
> "Now an unannounced outage from 6 to 9 pm. The rule-based controller loses 34.6 kilowatt-hours
> of critical load. GridGuard re-plans and loses 15. And those 15 are physically unavoidable: the
> critical load is 55 kilowatts but the battery can only deliver 50. You can see the gap here,
> where the purple line drops below the dotted critical-demand line. GridGuard reports
> shortfalls honestly instead of hiding them."
*(Outage sweep tab → Run sweep, or show the table)*
> "Across outage start times, it cuts lost critical energy by up to 89 percent."

**1:30–2:00 · Carbon** *(Carbon trade-off tab)*
> "On a sunny day, cost and carbon already agree, so a carbon price changes nothing. We say that
> openly. But on a monsoon day with a flat tariff, a cost-only controller has no reason to avoid
> dirty hours. GridGuard's carbon price cuts emissions by 4 percent at zero extra cost, by
> shifting grid use to cleaner hours."

**2:00–2:40 · Verifiable decisions** *(Audit ledger tab)*
> "Every decision goes into a SHA-256 hash-chained ledger."
*(click **Verify full chain** → green VALID)*
> "Valid."
*(click **Tamper test on a copy** → red)*
> "If anyone edits even one emissions number, verification fails at that record. But a local hash
> chain can't catch someone who rewrites everything, so GridGuard anchors the ledger's head hash
> in a smart contract on Ethereum's Sepolia testnet."
*(If anchored: click **Attack test: rewrite and re-hash a copy** → local check fooled, chain check FAILED. If not anchored, say:)* "That contract is built and tested on a simulated chain; deploying is one command."

**2:40–3:00 · Close** *(Constraint checks tab, all green)*
> "Everything is open source and reproducible: 81 tests, an independent physics validator, and
> identical results on different machines. All inputs here are synthetic, so these are simulated
> results, but the method is ready for real site data. GridGuard: cleaner, more resilient
> microgrids with decisions anyone can verify."

---

**Upload:** YouTube (Unlisted) or Vimeo. Paste the link into Devpost. Keep it under 3 minutes:
the IEEE page asks for 3 minutes and Devpost allows 3–5.
