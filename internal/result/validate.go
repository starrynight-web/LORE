package result

import (
	"bytes"
	"encoding/json"
	"fmt"
	"sync"

	"github.com/santhosh-tekuri/jsonschema/v6"
	"github.com/starrynight-web/LORE/schemas"
)

var (
	compileOnce sync.Once
	compiled    *jsonschema.Schema
	compileErr  error
)

func schema() (*jsonschema.Schema, error) {
	compileOnce.Do(func() {
		doc, err := jsonschema.UnmarshalJSON(bytes.NewReader(schemas.ResultV1))
		if err != nil {
			compileErr = err
			return
		}
		c := jsonschema.NewCompiler()
		if err := c.AddResource(schemas.ResultV1Name, doc); err != nil {
			compileErr = err
			return
		}
		compiled, compileErr = c.Compile(schemas.ResultV1Name)
	})
	return compiled, compileErr
}

// ValidateJSON checks raw JSON against lore.result/1.
func ValidateJSON(raw []byte) error {
	s, err := schema()
	if err != nil {
		return fmt.Errorf("compile schema: %w", err)
	}
	inst, err := jsonschema.UnmarshalJSON(bytes.NewReader(raw))
	if err != nil {
		return err
	}
	return s.Validate(inst)
}

// Validate checks an envelope against lore.result/1.
func Validate(e *Envelope) error {
	raw, err := json.Marshal(e)
	if err != nil {
		return err
	}
	return ValidateJSON(raw)
}
