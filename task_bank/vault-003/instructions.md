`vaultline inject` points at the wrong place when a template has a bad tag after its second line.
This template:

```
name: app
env: prod
key: {{ vault://acme/db }}
```

is rejected with "line 3, column 16", but the `{{` is at column 6 of line 3. Errors on the first two
lines point at the right column.
