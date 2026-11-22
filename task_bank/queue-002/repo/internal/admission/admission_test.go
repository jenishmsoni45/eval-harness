package admission_test

import (
	"errors"
	"math"
	"testing"
	"time"

	"github.com/jenishmsoni45/job-queue/internal/admission"
)

func TestFitsIsExactAtTheLimit(t *testing.T) {
	t.Parallel()
	for _, c := range []struct {
		backlog, limit, n int
		want              bool
	}{
		{0, 10, 10, true},
		{9, 10, 1, true},
		{10, 10, 1, false},
		{5, 10, 6, false},
		{5, 10, 5, true},
		{0, 1, 2, false},
		{math.MaxInt32, math.MaxInt32, 1, false}, // no overflow
	} {
		if got := admission.Fits(c.backlog, c.limit, c.n); got != c.want {
			t.Errorf("Fits(backlog %d, limit %d, adding %d) = %v, want %v", c.backlog, c.limit, c.n, got, c.want)
		}
	}
}

func TestRejectedIsAnError(t *testing.T) {
	t.Parallel()
	var err error = &admission.Rejected{Shop: "shop-a.test", Shed: 3, RetryAfter: time.Second}
	var rej *admission.Rejected
	if !errors.As(err, &rej) || rej.Shed != 3 {
		t.Fatalf("errors.As failed on %v", err)
	}
	if err.Error() == "" {
		t.Fatal("empty message")
	}
}
