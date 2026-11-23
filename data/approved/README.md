# data/approved/

Put one editor-approved news item per JSON file here (same fields as an item in
`app/data/content.json` → `news`). The `refresh` workflow moves it into the app
and deletes the file. Raw headlines in `data/inbox.json` must be rewritten in
Bahasa Indonesia (max. 3 sentences), linked to the source, and labelled
*Sumber resmi* or *Belum dikonfirmasi* first. Use `example.json.txt` as a template.

**Required media (no post without it):**

- `image`: `{url, credit, source}` — a jpeg/png URL (≤5 MB, HTTP 200) from the original
  article or official post (e.g. the article's `og:image`), never a YouTube thumbnail, never a
  file in this repo. `credit` = the photo caption credit, `source` = the page it appears on.
- `video`: `{url, title, channel, official: true, relation}` — an official YouTube video;
  `channel` must equal the YouTube oEmbed `author_name`. If there is no video about this exact
  news, use the artist's latest official video and say so in `relation`.

`refresh` checks both URLs live; failing files stay here (HOLD warning in the Actions log).
