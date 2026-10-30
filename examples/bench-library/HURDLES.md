# Why Lore lost

Same task, same model (`gpt-6-luna`, medium), every run passed the checklist. The numbers below are Codex `turn.completed` usage. `input_tokens` includes cached tokens. Fresh tokens are input minus cached. Logs are under `.tmp/bench-runs/`.

The twelve stable skill bodies are 33,532 tokens (139,649 characters). Their summaries are 349 tokens.

## Runs

### 1. First three-and-three (`results.json`)

| Arm | Median input | Median seconds |
| --- | ---: | ---: |
| Baseline, no Lore | 125,130 | 35.0 |
| Lore | 250,217 | 49.0 |

Ratio 2.0 on tokens, 1.4 on time. Cold map was 2.9s and was not in the timer.

Lore tools were `list_personas`, `get_context`, `locate`. Baseline tools were none. `get_context` was called with `frontend engineer` and answered `No persona named persona:frontend engineer`. The skill text never arrived. Each answer was about 2 KB of that miss.

Hurdle: a space in the persona name missed the folder `frontend-engineer`. The agent still paid for the tool rounds.

### 2. Rerun after the name fix, library only in an env var

`get_context` still returned no knowledge. Decisions were written to `/home/djrcx/.lore/decisions/dec-0010.md`, not the benchmark library. Codex did not apply `LORE_LIBRARY` to the server process, and the open folder had no knowledge store, so Lore walked up to the home directory.

Hurdle: the server has to find the persona files from the folder the editor opened. An env var on the MCP entry is not enough.

### 3. Valid rerun, library copied into the project (`results-rerun.json`)

| Arm | Input | Cached | Fresh | Seconds | Tools |
| --- | ---: | ---: | ---: | ---: | --- |
| Baseline | 82,309 | 40,960 | 41,349 | 49.9 | none |
| Lore | 468,014 | 438,912 | 29,102 | 52.7 | list_personas, get_context ×4, locate |

Ratio 5.7 on tokens. Time ratio 1.06, inside the 1.15 gate.

This time the skills arrived. Frontend used 258 of 800 tokens and returned all six stable skills plus map chunks. Accessibility used 142, backend 89, reviewer 65. `locate` was 988 characters. Tool results together are about 30 KB. Fresh tokens were lower than the baseline.

Hurdle: the standing rule tells the agent to call `list_personas`, then `get_context` once per step, then `locate`. Those are separate model rounds. Each round sends the prompt again, and Codex adds that send to `input_tokens` even when it is a cache hit. The skill bodies are not in this bill.

### 4. Read every skill file (`diagnostics.json`, arm `paste`)

242,643 input, 36,819 fresh, 62.6s, checklist passed. The agent ran `find` and `cat` over `.lore/skills`. One command result was 1,075,560 characters. That folder holds the draft skills as well as the twelve stable ones (191 files).

Hurdle for the measurement: "read the skills" is not the same as "read what Lore serves." Drafts sit beside stable skills, and an agent told to read the folder reads all of them. Lore's `get_context` does not return drafts.

### 5. Four `get_context` calls in one batch (`lore-steps`)

156,596 input, 19,892 fresh, 34.7s, checklist passed. Tools were four `get_context` calls and nothing else. No `list_personas`, no `locate`.

Hurdle this removes: the extra tools. Four calls issued together cost about the same as one call (run 6), not four times as much. The expensive pattern is a chain of rounds, not the number of tools inside one round.

### 6. One `get_context` (`lore-once`)

152,822 input, 25,846 fresh, 38.9s, checklist passed. One tool. The answer was 13,030 characters.

Against the chained run this is 152,822 / 468,014 = 0.33. Against the no-skill median of 125,130 it is 1.22. Against reading only the twelve files (run 7) it is 1.28.

Hurdle that remains: one tool call is still a second model round, and that round re-sends a prompt that now includes Lore's tool list. The payload itself is small.

### 7. Read only the twelve stable files (`paste-stable`)

119,769 input, 26,073 fresh, 28.2s, checklist passed. The `cat` of those twelve files returned 143,884 characters, and the next model message came after that result. The fresh tokens are the skill bodies. Lore did not beat this. One Lore call cost 33,053 more input tokens and 10.7 more seconds.

## What is not the cause

- The map. `locate` was under 1 KB, and the cold extract was 1–3 seconds, outside the timer.
- The 800-token cap. The largest answer used 258 tokens.
- Missing skill text, after runs 1 and 2 were fixed. Run 3 served the skills and lost by more.
- `get_skill`. It was never called.
- A full repo walk. The agents edited `Panel.tsx` and `health.py` and did not list the tree.

## Solution

Make one model round the normal path, and stop scoring Lore against an agent that loads nothing.

1. One call for the task. `get_context` should take the task sentence, pick the matching personas, return only the skill summaries that match that sentence, and include the file list that `locate` would return. The agent then edits. The standing text should say that, and should stop requiring `list_personas` and a later `locate`. Runs 5 and 6 show that a single round is about 153–157k tokens. Run 3 shows that a chain is 468k.

2. Keep the two fixes already in the code. Persona names fold spaces and capitals, so `frontend engineer` resolves. The benchmark copies the knowledge store into the project, because the server finds personas by walking up from the open folder.

3. Leave the budget, the persona set, and Graphify alone. None of the runs were lost because the answer was truncated or the map was wrong.

4. Score fresh tokens next to total input. On fresh tokens the chained Lore run (29,102) and the one-call run (25,846) already match the no-skill baseline (about 21,000–43,000). Total input counts every cached resend, so each extra round looks like a large loss.

5. Treat "read the twelve skill files" as the comparison that matches the product. Those files are 33,532 tokens and billed 119,769 in one read. One Lore call billed 152,822. The remaining gap is the tool list on the prompt, not the summaries (349 tokens). Shrinking the tool descriptions is the only change that can close that gap. Filtering which skills are returned cannot: the whole frontend answer was 258 tokens.

Lore wins when the other path is a chain of searches or a folder full of drafts (run 4, 242,643 tokens). It does not win on a three-file edit the model can do from memory, and it does not yet win against pasting the twelve stable files, because one tool round costs more than those files.

## After the solution

`get_context` with an empty persona now picks the personas named in the task, returns only skill summaries that share a word with it, and includes the files to open. The standing rule tells the agent to call that once. Tool descriptions are shorter. The new three-and-three is `results-solution.json`.

| Arm | Median input | Median fresh | Median seconds |
| --- | ---: | ---: | ---: |
| Baseline | 143,006 | 22,174 | 38.3 |
| Lore | 209,874 | 16,155 | 35.7 |

Checklist passed on all six runs. Cold map was 1.0s. Lore tools were one `get_context`, and on two runs a `get_skill` after it. No `list_personas` and no `locate`.

Input ratio 1.468. Fresh ratio 0.729. Time ratio 0.932. The time gate passes. The total-input gate does not. Fresh tokens are under the baseline. Against the chained run at 468,014 input, this is 209,874.
