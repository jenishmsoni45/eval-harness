//! The v1 vault encoder and decoder, byte for byte as `docs/vault-format.md`
//! §4.1–§4.4 specifies.
//!
//! Everything here treats its input as hostile (S10): no `unwrap`, `expect`,
//! indexing, `panic` or unchecked arithmetic, enforced by the lints below.
//! Lengths are checked against the bytes that are actually there before
//! anything is allocated. The functions are public so the `vault_file` fuzz
//! target can call them directly, without Argon2 in the way.

#![deny(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::panic,
    clippy::arithmetic_side_effects
)]

use std::fmt;

pub const MAX_NAME_LEN: usize = 64;

/// A project, item or field name: 1–64 bytes from `A–Z a–z 0–9 . _ -`,
/// case-sensitive (§4.3, D-027). Names are metadata, not secrets: they are
/// encrypted in the file but may be printed.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Name(String);

/// Why a string is not a valid [`Name`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NameError {
    /// The name is empty.
    Empty,
    /// The name is longer than 64 bytes.
    TooLong,
    /// The name contains a byte outside `A–Z a–z 0–9 . _ -`.
    BadByte,
}

impl fmt::Display for NameError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            NameError::Empty => "a name can't be empty",
            NameError::TooLong => "a name can be at most 64 bytes long",
            NameError::BadByte => "a name may only use the characters A-Z a-z 0-9 . _ -",
        })
    }
}

impl std::error::Error for NameError {}

impl Name {
    /// Validates a name.
    pub fn new(name: &str) -> Result<Self, NameError> {
        Self::from_bytes(name.as_bytes())
    }

    /// Validates a name given as bytes.
    pub fn from_bytes(bytes: &[u8]) -> Result<Self, NameError> {
        if bytes.is_empty() {
            return Err(NameError::Empty);
        }
        if bytes.len() > MAX_NAME_LEN {
            return Err(NameError::TooLong);
        }
        if !bytes
            .iter()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
        {
            return Err(NameError::BadByte);
        }
        // Every byte is ASCII, so this can't fail; map the error anyway.
        String::from_utf8(bytes.to_vec())
            .map(Name)
            .map_err(|_| NameError::BadByte)
    }

    /// The name as a string.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for Name {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
