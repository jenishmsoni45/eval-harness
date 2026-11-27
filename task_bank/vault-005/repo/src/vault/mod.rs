//! The vault library: create, open, get, set, rm, list, passwd and rotate
//! (`docs/vault-format.md` §4, `docs/architecture.md` §1).
//!
//! A [`Vault`] holds only the unlocked master key and where the vault lives.
//! Every operation re-reads the file and re-verifies it under that key, and
//! every change happens under the writer lock as read, modify, replace. Two
//! writers therefore take turns and never lose each other's changes, and a
//! file swapped underneath is noticed.

pub mod format;

pub use format::{Name, NameError};
