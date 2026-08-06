# Title and description handoff

## Input

- Active Manuscript Package v1 reference, version and SHA-256.
- Final target-language script and approved story facts.
- Channel, region, audience, platform and packaging brief.

## Title Asset v1

Save a versioned JSON document containing:

- `contractType: title-asset-v1`;
- project, channel, language and manuscript identity;
- six candidates by default, each with strategy, factual evidence and six-part score;
- exactly one confirmed title when confirmation is available;
- prompt bundle version and SHA-256;
- canonical content SHA-256 and status `TITLE_READY`.

## Description Asset v1

Save a versioned JSON document and a copy-ready text file containing:

- `contractType: description-asset-v1`;
- the final description body in the target language;
- 8–12 factual Hashtags unless the user explicitly opts out;
- the combined copy-ready text;
- factual evidence, prohibited claims and spoiler boundary;
- project, channel, language and manuscript identity;
- prompt bundle version and SHA-256;
- canonical content SHA-256 and status `DESCRIPTION_READY`.

## Description adaptation

The bundled v2.1 prompt defines a story introduction, not a YouTube description. Use its core-material extraction and hook strategy only for the first two description lines. Then add a concise promise, story scope and viewing payoff. Do not copy a full opening scene into metadata and do not reveal a protected ending.

Both assets must bind the same active Manuscript Package. A manuscript revision invalidates both assets. `publishing-assets` must reject missing confirmation, mismatched hashes or claims unsupported by the final script.
