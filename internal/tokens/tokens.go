// Package tokens counts tokens with the cl100k_base encoding, loaded offline.
package tokens

import (
	"sync"

	"github.com/pkoukk/tiktoken-go"
	tiktoken_loader "github.com/pkoukk/tiktoken-go-loader"
)

var (
	once sync.Once
	enc  *tiktoken.Tiktoken
)

func encoder() *tiktoken.Tiktoken {
	once.Do(func() {
		tiktoken.SetBpeLoader(tiktoken_loader.NewOfflineLoader())
		e, err := tiktoken.GetEncoding("cl100k_base")
		if err == nil {
			enc = e
		}
	})
	return enc
}

// Count returns the token count of s. If the encoder is unavailable it falls
// back to a conservative estimate of one token per three bytes.
func Count(s string) int {
	if e := encoder(); e != nil {
		return len(e.Encode(s, nil, nil))
	}
	return (len(s) + 2) / 3
}
