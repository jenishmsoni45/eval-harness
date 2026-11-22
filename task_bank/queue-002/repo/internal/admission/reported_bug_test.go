package admission_test

import (
	"testing"
	"time"

	"github.com/jenishmsoni45/job-queue/internal/admission"
)

// The reported problem: a shop whose backlog_retry_after_ms is 1500 gets Retry-After: 1, so its
// clients come back half a second early and are refused again.
func TestRetryAfterForOneAndAHalfSecondsIsTwo(t *testing.T) {
	t.Parallel()
	if got := admission.RetryAfterSeconds(1500 * time.Millisecond); got != 2 {
		t.Fatalf("RetryAfterSeconds(1.5s) = %d, want 2", got)
	}
}
