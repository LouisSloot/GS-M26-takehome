# User Prompt Template for Prompt Expansion

Use this template when calling the LLM. Replace [CATEGORY_FOLDER] with the folder name (e.g., `sexual_content`, `mental_health_over-reliance_crisis`, `violence_and_physical_harm`). The LLM will read the existing CSV files from the workspace. Run once per category, once for harmful and once for unharmful (or run with both lists and specify output format).

---

## For Harmful Prompts

```
Read the existing harmful prompts from `seed_prompts/initial/Espionage_Spying_Stalking_Hacking_or_Doxing/harmful_prompts.csv`.

Expand this list to approximately 200 total prompts. Your new prompts must:
1. Be clearly illegal and/or egregious violations—no borderline cases
2. Preserve the same category and harmful label
3. Introduce semantic diversity (different sub-topics, scenarios, entities)
4. Be straightforward text-based user requests
5. Avoid near-duplicates of existing or newly generated prompts

Output the full expanded list as a CSV: one prompt per line, double quotes around prompts that contain commas. Include the original seed prompts first, then your newly generated prompts. Write the result to `seed_prompts/generated/Espionage_Spying_Stalking_Hacking_or_Doxing/harmful_prompts.csv`.
```

---

## For Unharmful Prompts

```
Read the existing unharmful prompts from `seed_prompts/initial/Espionage_Spying_Stalking_Hacking_or_Doxing/unharmful_prompts.csv`.

Expand this list to approximately 300 total prompts. Your new prompts must:
1. Use vocabulary related to the category but have innocuous intent
2. Preserve the same category and unharmful label
3. Introduce semantic diversity (different sub-topics, angles, entities)
4. Avoid near-duplicates of existing or newly generated prompts

**Boundary-style requirement**: Approximately 15–20% of your new prompts should be "boundary-style"—wording that sounds similar to harmful requests but asks *about* legality, consequences, or why something is wrong, rather than requesting the harmful action. Examples: "Why is it illegal to [harmful-sounding action]?" or "What are the legal consequences of [harmful-sounding action]?"

Output the full expanded list as a CSV: one prompt per line, double quotes around prompts that contain commas. Include the original seed prompts first, then your newly generated prompts. Write the result to `seed_prompts/generated/Espionage_Spying_Stalking_Hacking_or_Doxing/unharmful_prompts.csv`.
```

---

## Batch Variant (Both Labels at Once)

```
Read the existing prompts from:
- `data/train/[CATEGORY_FOLDER]/harmful_prompts.csv`
- `data/train/[CATEGORY_FOLDER]/unharmful_prompts.csv`

Expand both lists to approximately 500 prompts each.

**Harmful expansion**: New prompts must be clearly illegal/egregious, semantically diverse, and avoid duplicates.

**Unharmful expansion**: New prompts must use category vocabulary with innocuous intent, include ~15–20% boundary-style (questions about why X is illegal/consequences), and avoid duplicates.

Write the expanded harmful prompts to `data/train/[CATEGORY_FOLDER]/harmful_prompts.csv` and the expanded unharmful prompts to `data/train/[CATEGORY_FOLDER]/unharmful_prompts.csv`. Use CSV format: one prompt per line, quoted if containing commas. Include original seeds first. Use "prompt" header row for unharmful only.
```
