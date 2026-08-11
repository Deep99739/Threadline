# Continuation dataset v0.1

This dataset freezes the initial behavioral contract before retrieval or UI tuning. It is synthetic and contains no private repositories, credentials, or user data.

- **Cases:** 30
- **Purpose:** drive the local vertical slice and protect trust invariants
- **Status:** development set; a held-out test split will be created before model/ranker tuning
- **Labels:** manually specified from the locked Threadline requirements

Each case declares an exact repository, branch, commit, caller scope, evidence set, required state, next action, abstention behavior, required evidence, and forbidden evidence. Implementations may improve ranking but must not rewrite labels merely to pass.
