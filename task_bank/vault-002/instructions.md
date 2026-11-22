`envfile::parse` rejects an env file whose comment lines are indented. A file with
`  # the database` on its first line and `DB_URL=vault://acme/db/url` on the second fails with
"line 1: expected NAME=value, a # comment or a blank line". The grammar at the top of the module
allows spaces and tabs before the `#` of a comment, so I expected the comment to be skipped and
the file to load with its one assignment.
