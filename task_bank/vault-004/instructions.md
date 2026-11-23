A secret is printed in clear when its value repeats a few of its own bytes and the child's output
arrives in pieces.

If the whole output arrives in one read, the secret is masked correctly. If a read happens to end
partway through the secret, the secret can come through unmasked, depending on the bytes just
before it.

For example, with the secret `xxxyyy`, a child that writes `zxxxx` and then `xyyyz` in a separate
write should produce `zxx<concealed by vaultline>z`. Instead it produces `zxxxxxyyyz`.
