package queue_test

import (
	"testing"
	"time"

	"github.com/jenishmsoni45/job-queue/internal/queue"
)

// The reported problem: with a 500 ms base, a job that failed once can wait up to 1 s before its
// retry, twice the base.
func TestTheBoundAfterOneFailureIsTheBase(t *testing.T) {
	b := queue.Backoff{Base: 500 * time.Millisecond, Cap: time.Minute}
	if got := b.Bound(1); got != 500*time.Millisecond {
		t.Fatalf("Bound(1) = %v, want 500ms", got)
	}
}
