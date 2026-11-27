`vaultline run --env-file` rejects env files whose values contain an `=` sign. A file with the line
`SESSION_SECRET=dG9rZW4=` (a base64 value with its padding) fails with "line 1: a variable name
starts with a letter or _ and then uses letters, digits and _", and so does
`DATABASE_URL=postgres://db/app?sslmode=require`. The variable names are fine. Values are meant to
be taken literally, so I expected both lines to load with everything after the name and its `=`
as the value.
