//! The reported problem: an env file whose comment lines are indented is rejected.

use vaultline::inject::envfile::parse;

#[test]
fn an_indented_comment_before_an_assignment_is_skipped() {
    let parsed = parse(b"  # the database\nDB_URL=vault://acme/db/url\n").unwrap();
    assert_eq!(parsed.len(), 1);
    assert_eq!(parsed[0].name, "DB_URL");
}
