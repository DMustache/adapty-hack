# Discount Advisor: 3-minute demo script

**Setup before going on stage** (about 1 minute)
1. `cd discount_advisor` → `..\.venv\Scripts\python.exe -m streamlit run app.py` → open http://localhost:8501
2. Leave the sidebar at its defaults (placement **onboarding**, first paid payment, 12 months).
3. Optional second tab: the Adapty dashboard with the **Lumen** app selected.

Numbers below are what the app shows with default settings. If you change a slider, read the screen, not the script.

---

## 0:00 – The question (20 s)
> "Every subscription app gets asked: *should we offer a discount, and how big?* Most tools answer with the
> discount that brings the most buyers. We wanted the one that brings the most **revenue**, and we wanted to be
> honest about what the data can and can't tell us."

## 0:20 – Why you can't just learn it from the data (40 s)
**Click: Data reality check**
> "This is Adapty's hackathon dataset: 50,000 users, 30,000 purchases. It's synthetic. It has **no discount
> exposure at all**: one price per product per country."

Point at the chart:
> "The only price variation is regional. And cheaper countries convert *less*. A naive model would conclude
> that raising prices increases sales. That's **confounding**: country drives both price and willingness to pay.
> So we don't train a model on it. We'd be confidently wrong."

## 1:00 – What we *can* compute exactly (40 s)
**Click: Recommendation**. Point at the blue / violet / orange labels:
> "Every number is labelled: **DATA** measured, **CALCULATED** exact arithmetic, **ASSUMED** your belief."

Point at the table, "Break-even lift" column:
> "From the data alone we know exactly what a discount must achieve. On the onboarding paywall, 35% off on the
> first payment only pays if conversion rises by at least **34%**: from 16.8% to about 22.5%. That part isn't
> a guess. It comes from measured conversion, plan mix and renewal curves."

## 1:40 – The unknown, made explicit (40 s)
**Click: Sensitivity**
> "What we *don't* know is how customers respond. So that's an explicit input, with a range. This heatmap shows
> the best discount under every possible response. Below a 17% response, full price always wins. Across our
> assumed range, the winner is split between full price, 35% and 40%. **The data can't settle it.**"

## 2:20 – So: design the experiment (30 s)
**Click: Recommendation**, headline + decision rule:
> "So the tool doesn't say '35% is optimal'. It says: **this is worth testing**: 751 users per arm, about
> 3 weeks, roll out only if conversion clears break-even and revenue guardrails hold. Fixed before launch."

Optional, if time (**click: Live Adapty**):
> "And it's wired to Adapty. We seeded real Adapty apps with these users, 5,000 and 50,000, and verified every
> profile matches. We even ran the A/B test pipeline with *simulated* users: 150 users show a meaningless −0.5
> point difference. That's exactly why the tool sizes tests in the hundreds per arm."

## 2:50 – Close (10 s)
> "Measure what you can, calculate what's exact, be explicit about what you assume, and **let an experiment
> decide**. That's Discount Advisor."

---

## Likely questions
| Question | Answer |
|---|---|
| *Why not ML?* | No discount variation in the data; regional prices are confounded. A model would learn the wrong sign. |
| *Why can the best discount fall when response is huge?* | A modest discount already reaches most possible buyers (market ceiling); deeper ones subsidise people who'd buy anyway. |
| *What about costs?* | Sidebar "Variable cost per paid period": a discount cuts price, not cost, so break-even rises. The data has no costs, so the default is 0. |
| *Is the live A/B result real?* | No. Simulated users, labelled as such. It proves the pipeline, not the discount. |
| *What's synthetic?* | All of it: the fictional Lumen app from the hackathon organisers. |
| *Annual plans?* | 120 days of data can't show annual renewals; they count as one payment, and the app warns about it. |
