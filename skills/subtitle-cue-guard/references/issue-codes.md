# Issue codes

Every issue in `check` output has `id` (cue number, counted from 1 in file order), `code`, `severity` and a `message` in the chosen screen language. Codes and keys are the same in every language.

| Code | Severity | Meaning | In `retry` |
|---|---|---|---|
| `missing` | error | The source cue id is absent from the translation. | yes |
| `unexpected_id` | error | The translation has an id the source lacks (often a split cue). Check the ids, not the text. | no |
| `empty` | error | No visible text (only tags or whitespace). Usually the merge victim of the cue before it. | yes |
| `untranslated` | error | Same as the source (`reason: same_as_source`) or no characters of the target script (`reason: wrong_script`). Single words and cues without letters are exempt (`kept_as_is`, severity info). | yes |
| `tag_mismatch` | error | The formatting tags (`<i>`, `<v Anna>`, `{\an8}`) differ from the source. Restore the placeholders. | yes |
| `number_mismatch` | error | A number of the source is missing in the translation (full-width digits and thousands commas are normalised). | yes |
| `shift_suspect` | suspect | The translation contains a number that exists only in a neighbouring source cue: content probably moved. The cue and that neighbour are retried. | both |
| `merge_suspect` | suspect | The sentence count grew and the cue is far longer than the file's median ratio, or the next cue is empty and the cue is long. The cue and the next one are retried. | both |
| `cps` | warn | Characters per second above the limit (value and limit are in the issue). | yes |
| `too_many_lines` | warn | More lines than allowed. | yes |
| `line_width` | warn | A line is wider than the limit. | yes |
| `overlap`, `out_of_order`, `nonpositive_duration`, `stray_block` | source | Problems already present in the source file (listed in `source_issues`). Nothing to retranslate; mention them to the user. | no |

`ok` is true only when no error, suspect or warn issue is left. With `--no-retry-readability` the three readability warnings stay in the list but no longer affect `ok`, the exit code or `retry`.

## What to do

- Retranslate exactly the cues in `retry`, with `--context 1`, and nothing else.
- For a `merge_suspect` pair, translate each cue separately and keep the sentence of cue N in cue N.
- `assemble` refuses only on errors and suspects; `--fallback source` keeps the source text for every cue in `retry` that is not a pure readability warning.
