// Package auth issues and verifies access tokens for the demo app.
package auth

import (
	"errors"
	"time"
)

var ErrExpired = errors.New("token expired")

type Claims struct {
	Subject   string
	ExpiresAt time.Time
}

// IssueAccessToken returns claims for a short-lived access token.
func IssueAccessToken(subject string, now time.Time) Claims {
	return Claims{Subject: subject, ExpiresAt: now.Add(15 * time.Minute)}
}

// Verify checks that the claims have not expired.
func Verify(c Claims, now time.Time) error {
	if now.After(c.ExpiresAt) {
		return ErrExpired
	}
	return nil
}
