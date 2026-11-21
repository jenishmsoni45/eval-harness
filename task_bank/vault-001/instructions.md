Part of a secret is printed in clear when two secrets overlap and the child's output arrives in
pieces.

When a child process prints one secret and the end of that secret is also the start of another
secret, the tail of the first secret sometimes appears in plain text right after the
`<concealed by vaultline>` marker. It depends on how the output is split into reads: if the whole
output arrives in one read, it is masked correctly.

For example, with the secrets `alpha-77` and `77-omega`, a child that writes `alpha-77`, then
`-om` in a separate write, then ` done` produces `<concealed by vaultline>77-om done`. I expect
`<concealed by vaultline>-om done`.
