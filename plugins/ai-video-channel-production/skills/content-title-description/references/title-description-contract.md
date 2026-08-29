# Title and description handoff

## Input

- Active Manuscript Package v1 reference, version and SHA-256.
- Final target-language script and approved story facts.
- Channel, region, audience, platform and packaging brief.

## Title source and optional Title Asset v1

The normal production route uses the confirmed narration title as the single publishing title. Store its target-language text, Chinese review translation, narration binding and SHA-256 with the narration record. Do not create alternative title candidates or require a separate Title Asset merely because production has started.

Create Title Asset v1 only when the user explicitly requests title generation or optimization, or when the narration has no usable title and the user chooses the title generator.

Save a versioned JSON document containing:

- `contractType: title-asset-v1`;
- project, channel, language and manuscript identity;
- exactly six generated candidates, each with target-language text, Chinese translation, strategy, factual evidence and six-part score;
- exactly one confirmed title when confirmation is available;
- prompt bundle version and SHA-256;
- canonical content SHA-256 and status `TITLE_READY`.

## Description Asset v1

Save a versioned JSON document and a copy-ready text file containing:

- `contractType: description-asset-v1`;
- the final description body in the target language;
- a complete Chinese review translation stored outside the formal YouTube fields;
- 8–12 factual Hashtags only when the user explicitly asks for Hashtags; otherwise save an empty list;
- a one-to-one Chinese meaning for every Hashtag, stored outside the formal YouTube fields;
- the combined copy-ready text;
- factual evidence, prohibited claims and spoiler boundary;
- project, channel, language and manuscript identity;
- prompt bundle version and SHA-256;
- canonical content SHA-256 and status `DESCRIPTION_READY`.

## Description adaptation

The bundled v2.1 prompt defines a story introduction, not a YouTube description. Use its core-material extraction and hook strategy only for the first two description lines. Then add a concise promise, story scope and viewing payoff. Do not copy a full opening scene into metadata and do not reveal a protected ending.

## Thumbnail Asset v1

Only after the user explicitly requests a custom thumbnail, resolve exactly one title—normally the confirmed narration title, or a user-confirmed generated title when explicitly requested—and generate five materially different 16:9 thumbnail candidates with the image and target-language short copy created together by `imagegen`. If the user did not request a custom thumbnail, save `thumbnail.mode=youtube_auto`, create no image candidates, and do not call `imagegen`. When requested, save:

- `contractType: thumbnail-asset-v1`;
- project, channel, language, manuscript and confirmed-title identity;
- candidate image paths, dimensions, sizes, SHA-256 values and visual-quality checks;
- the Chinese meaning of the selected target-language thumbnail short copy;
- the selected candidate and confirmation record;
- prompt bundle version and SHA-256;
- status `THUMBNAIL_READY`.

Inspect every generated image with `view_image`. Reject or regenerate text errors, illegible mobile composition, unsupported story claims, malformed people, wrong aspect ratio and placeholder output. A title or manuscript revision invalidates the thumbnail asset.

Every asset that is actually generated must bind the same active Manuscript Package. The inherited narration-title record must bind the same source manuscript version and hash. `publishing-assets` must reject missing Chinese review mappings for fields that actually exist, mismatched hashes, unsupported claims or an invalid requested custom thumbnail, but must not reject a project merely because it omitted title candidates, description, Hashtags or a custom thumbnail. Save only the review documents that apply; never copy Chinese review text into target-language YouTube upload fields.
