# SRT and WebVTT notes

The parser reads files as UTF-8 and keeps every line it does not translate exactly as it was. Re-saving through a generic subtitle library usually loses some of this; assembling here does not.

- **BOM and line endings.** A leading BOM, CRLF or LF endings and a missing final newline are preserved. Inserted lines use the line ending of the cue's timing line.
- **Cue ids.** Cue ids in the tool are positions (1, 2, 3 ...) in file order, whatever number the SRT file shows. Duplicate or skipped numbers are kept as they are unless you pass `--renumber`.
- **Blank lines.** Several blank lines between cues are fine. A block without a timing line (for example text after a blank line inside a cue) is kept untouched and reported as `stray_block`.
- **Time codes.** `,` and `.` separators, hours of more than two digits and WebVTT times without hours are accepted. A time line that starts like a time but does not parse (for example `->` instead of `-->`) stops the run with exit code 2 and the line number.
- **WebVTT extras.** The `WEBVTT` header with its metadata lines, `NOTE`, `STYLE` and `REGION` blocks, cue identifiers and cue settings (`align:start line:10%`) are never changed. `<v Anna>`, `<c.yellow>` and `<00:00:01.000>` tags are protected like `<i>`.
- **ASS tags in SRT.** `{\an8}` style override blocks are treated as tags and replaced by placeholders while the model translates.
- **What gets normalised.** Translation text is stripped per line, blank lines are dropped and `-->` inside a translation becomes `->`, so a translation can never create a new cue.
- **Not supported.** ASS/SSA, TTML, SBV, and automatic re-wrapping of long lines (overlong lines are reported so the cue is translated again).
