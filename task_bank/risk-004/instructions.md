A rule file that gives the same key twice in one place is accepted without a word. A rule written
with `action: hold` on one line and `action: block` on the next loads as a block rule, and a file
with `version: 1` at the top and `version: 2` further down loads as version 2. I expected loading
such a file to fail with a message naming the repeated key and its line, the way every other
mistake in the file is reported.
