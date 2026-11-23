//! vaultline: an encrypted local vault that injects secrets into child
//! processes and templates without writing plaintext to disk.
//!
//! The design lives in `docs/`.

#![forbid(unsafe_code)]

#[cfg(not(unix))]
compile_error!("vaultline supports Unix only (macOS and Linux); Windows is not supported (D-021)");

pub mod inject;
pub mod secret;
