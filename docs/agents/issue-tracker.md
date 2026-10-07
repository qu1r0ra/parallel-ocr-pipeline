# Issue tracker: GitHub

Issues and published specs live in GitHub Issues for
`qu1r0ra/parallel-ocr-pipeline`. Use the `gh` CLI.

## Operations

Run commands inside this repository so `gh` resolves its remote.

- Create: `gh issue create --title "..." --body-file <file>`
- Read: `gh issue view <number> --comments`
- List: `gh issue list --state open --json number,title,body,labels,assignees`
- Comment: `gh issue comment <number> --body-file <file>`
- Label: `gh issue edit <number> --add-label "..."`
- Remove label: `gh issue edit <number> --remove-label "..."`
- Close: `gh issue close <number> --comment "..."`

Use UTF-8 files with actual newlines for multiline bodies.

When a skill says to publish to the issue tracker, create a GitHub issue.
When it says to fetch a ticket, read the issue and its comments.

## Pull requests as a triage surface

PRs as a request surface: no.

GitHub issues and PRs share a number space. When the type is unclear,
try `gh pr view <number>` and fall back to `gh issue view <number>`.
