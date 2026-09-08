# Drive images job — context for the next session

## What this is
Shadi's Google Doc (https://docs.google.com/document/d/1RNTtZfQgviER0kUwf3QOA7rsBB3MqIar3kH5LwlUXOQ/edit) lists images for 385 blog articles on shadihossam.com. 165 of them have all their images on Google Drive (the rest are on Envato — skip those, Shadi is handling those himself).

`manifest.json` in this folder is the parsed list of those 165 Drive-only articles: article number, slug, title, the local `.md` content file path (in the shadi-hossam-astro repo), and the 3 Google Drive file IDs for that article (in doc order).

## The established pattern (copied from 89 articles already done this way)
Astro project: `/Users/chadihossam/Documents/Claude Code Project/shadi-hossam-website/shadi-hossam-astro`

For each article's 3 images, in order:
1. **Image 1** → save as `public/images/blog/<basename>/1.webp` (where `<basename>` = the .md filename without extension, e.g. `90-day-ai-plan-uae`). Add to frontmatter, right after the `category:` line: `image: "/images/blog/<basename>/1.webp"`
2. **Image 2** → save as `.../2.webp`. Insert into the body as `![<article title>](/images/blog/<basename>/2.webp)` immediately after the "## Key Takeaways" section — i.e. right before the next `## ` heading that follows Key Takeaways.
3. **Image 3** → save as `.../3.webp`. Insert as `![<article title>](/images/blog/<basename>/3.webp)` immediately before the `## FAQ` heading.

Look at an already-done example for the exact shape, e.g. `src/content/blog/en-AE/ai-ad-creative-uae.md`.

## The blocker that stopped the previous session
Google Drive file IDs in the doc returned "Requested entity was not found" via the `Google Drive` MCP connector — the connected account didn't have access to those specific files. Shadi said he opened up access on the files. **First thing to do in the new session: test 2-3 drive_ids from manifest.json with the Google Drive MCP tool (get_file_metadata or read_file_content) to confirm access now works before doing anything else.**

## Execution plan once access is confirmed
- ~495 images to download total (165 × 3). This is a lot of tool calls — likely worth splitting into batches across parallel background Agents (general-purpose, since they need MCP + Bash + Edit) rather than doing it all in the main session context.
- Each drive image needs converting to `.webp` — `cwebp` is installed on this machine, or Python PIL (`pip` env already has Pillow 10.4.0).
- Mark each manifest entry `"done": true` as it's completed, so the job is resumable if interrupted again.
- Note: one article (num 1, "90-day-ai-plan") shares a drive_id with article num 3 ("ab-test-sample-size") in the raw doc — looked like a possible copy-paste duplicate in the original doc. Not blocking, just flagging in case an image looks reused.
