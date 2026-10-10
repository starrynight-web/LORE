// Package schemas embeds the published JSON Schemas.
package schemas

import (
	_ "embed"
	"encoding/json"
)

//go:embed lore.result.v1.json
var ResultV1 []byte

// ResultV1Name is the file name used under .lore/schemas/ and in lore://schemas/.
const ResultV1Name = "lore.result.v1.json"

// ResultV1Map returns the result schema decoded as a generic map, the form the
// MCP SDK accepts as a tool OutputSchema.
func ResultV1Map() map[string]any {
	var m map[string]any
	if err := json.Unmarshal(ResultV1, &m); err != nil {
		panic("embedded lore.result.v1.json is invalid: " + err.Error())
	}
	return m
}
