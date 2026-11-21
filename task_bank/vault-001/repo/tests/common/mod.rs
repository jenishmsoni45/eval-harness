//! Helpers shared by the integration test binaries. Every passphrase and
//! value is fake, and every vault lives in its own temporary directory
//! (`docs/design.md` §12.2).

#![allow(dead_code)]

/// Whether `needle` occurs in `haystack`.
pub fn contains(haystack: &[u8], needle: &[u8]) -> bool {
    needle.is_empty() || haystack.windows(needle.len()).any(|w| w == needle)
}
