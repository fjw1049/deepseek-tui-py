# Skills Lint Report

- Skills root: `/Users/user/.deepseek/skills`
- Skills found: 26
- Errors (code/parity bugs): 0
- Warnings (content quality): 5

| Severity | Skill | Check | Reason |
|---|---|---|---|
| warn | Humanizer | name_matches_directory | frontmatter name='humanizer-zh' != dir='Humanizer' |
| warn | template | name_matches_directory | frontmatter name='template-skill' != dir='template' |
| warn | Humanizer | description_single_line | uses block scalar (\| or >) — parser drops continuation lines; rewrite description as a single line |
| warn | training-dataset-builder | description_single_line | uses block scalar (\| or >) — parser drops continuation lines; rewrite description as a single line |
| warn | template | body_nonempty | body is 27 chars (<50) |
