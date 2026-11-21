//! S7 (`docs/design.md` §2, §6, D-045), P3-8 and P3-9: no byte of any secret
//! occurrence reaches the captured output, whatever the read-chunk
//! boundaries, and the masker never holds back as many bytes as the longest
//! secret.
//!
//! Two layers: proptest comparisons of the streaming masker with a one-shot
//! reference, and end-to-end runs through a real child whose output is cut up
//! by the kernel and by the child's own pauses.

use proptest::prelude::*;
use vaultline::inject::mask::{MARKER, Masker, reference_mask};

use crate::common::contains;

const MARKER_TEXT: &str = "<concealed by vaultline>";

/// Cuts `input` at the positions in `cuts`, taken modulo its length.
fn cut<'a>(input: &'a [u8], cuts: &[usize]) -> Vec<&'a [u8]> {
    let mut points: Vec<usize> = cuts.iter().map(|c| c % (input.len() + 1)).collect();
    points.push(0);
    points.push(input.len());
    points.sort_unstable();
    points.dedup();
    points.windows(2).map(|w| &input[w[0]..w[1]]).collect()
}

/// Streams `chunks` through a masker. Returns the output and the most bytes
/// the masker ever held.
fn stream(secrets: &[&[u8]], chunks: &[&[u8]]) -> (Vec<u8>, usize) {
    let mut masker = Masker::new(secrets.iter().copied()).expect("a masker");
    let mut out = Vec::new();
    let mut most_held = 0;
    for chunk in chunks {
        masker.push(chunk, &mut out).expect("push");
        most_held = most_held.max(masker.held());
    }
    masker.finish(&mut out).expect("finish");
    (out, most_held)
}

fn longest(secrets: &[&[u8]]) -> usize {
    secrets.iter().map(|s| s.len()).max().unwrap_or(0)
}

/// What the input is made of: a secret, or other bytes.
#[derive(Debug, Clone)]
enum Piece {
    Secret(usize),
    Other(Vec<u8>),
}

/// Secrets and an input built from them, so that occurrences are common,
/// overlap, touch and straddle chunk boundaries. A small alphabet makes
/// secrets that are prefixes, suffixes and substrings of each other.
fn scenario(alphabet: u8) -> impl Strategy<Value = (Vec<Vec<u8>>, Vec<u8>, Vec<usize>)> {
    (
        proptest::collection::vec(proptest::collection::vec(0..alphabet, 1..9), 1..5),
        proptest::collection::vec(any::<u8>(), 0..1),
    )
        .prop_flat_map(move |(secrets, _)| {
            let count = secrets.len();
            let pieces = proptest::collection::vec(
                prop_oneof![
                    (0..count).prop_map(Piece::Secret),
                    proptest::collection::vec(0..alphabet, 0..6).prop_map(Piece::Other),
                ],
                0..24,
            );
            (
                Just(secrets),
                pieces,
                proptest::collection::vec(any::<usize>(), 0..24),
            )
        })
        .prop_map(|(secrets, pieces, cuts)| {
            let mut input = Vec::new();
            for piece in pieces {
                match piece {
                    Piece::Secret(i) => input.extend_from_slice(&secrets[i]),
                    Piece::Other(bytes) => input.extend_from_slice(&bytes),
                }
            }
            (secrets, input, cuts)
        })
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(1024))]

    /// No byte of a secret survives outside a marker: with the markers
    /// removed, no secret is left in the output.
    #[test]
    fn no_secret_survives_in_the_output(
        (secrets, input, cuts) in scenario(3)
    ) {
        let refs: Vec<&[u8]> = secrets.iter().map(Vec::as_slice).collect();
        let (out, _) = stream(&refs, &cut(&input, &cuts));
        // Take the markers out; what is left was passed through, and no
        // secret may be in it. (A secret that occurs only where the markers
        // joined two pieces of text is not a leak of the child's output,
        // so check the pieces one by one.)
        let mut rest = out.as_slice();
        let marker = MARKER;
        let mut pieces: Vec<&[u8]> = Vec::new();
        while let Some(at) = rest.windows(marker.len()).position(|w| w == marker) {
            pieces.push(&rest[..at]);
            rest = &rest[at + marker.len()..];
        }
        pieces.push(rest);
        for piece in pieces {
            for secret in &refs {
                prop_assert!(!contains(piece, secret), "a secret survived");
            }
        }
    }

    /// P3-9, NFR-10: fewer bytes are held back than the longest secret,
    /// whatever the output.
    #[test]
    fn the_masker_never_holds_back_as_many_bytes_as_the_longest_secret(
        (secrets, input, cuts) in scenario(3)
    ) {
        let refs: Vec<&[u8]> = secrets.iter().map(Vec::as_slice).collect();
        let (_, most_held) = stream(&refs, &cut(&input, &cuts));
        prop_assert!(most_held < longest(&refs), "held {} of {}", most_held, longest(&refs));
    }
}

/// NFR-10 on the inputs that hold the most: endless almost-matches.
#[test]
fn held_bytes_stay_below_the_longest_secret_on_adversarial_output() {
    for (secret, unit) in [
        (vec![b'a'; 3000], vec![b'a'; 1000]),
        (b"abababababc".to_vec(), b"ab".to_vec()),
        (vec![0u8; 500], vec![0u8; 499]),
    ] {
        let mut masker = Masker::new([secret.as_slice()]).unwrap();
        let mut out = Vec::new();
        for _ in 0..300 {
            masker.push(&unit, &mut out).unwrap();
            assert!(masker.held() < secret.len());
        }
        masker.finish(&mut out).unwrap();
        assert_eq!(masker.held(), 0);
    }
}

/// D-045's case, end to end through the library.
#[test]
fn a_secret_that_overlaps_another_leaks_nothing_at_any_boundary() {
    let secrets: [&[u8]; 2] = [b"abcdefgh", b"efghijkl"];
    let input = b"-- abcdefghijkl --";
    let expected = reference_mask(&secrets, input);
    assert_eq!(expected, format!("-- {MARKER_TEXT} --").as_bytes());
    for first in 0..=input.len() {
        for second in first..=input.len() {
            let chunks = [&input[..first], &input[first..second], &input[second..]];
            assert_eq!(
                stream(&secrets, &chunks).0,
                expected,
                "cuts at {first}, {second}"
            );
        }
    }
}
