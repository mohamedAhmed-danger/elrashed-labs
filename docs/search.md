# Search

The search module is responsible for retrieving relevant laboratory services from the database.

It combines **fuzzy search** and **semantic search**, then merges the results before building the RAG context.

## Flow

```text
Refined Queries
      ↓
ContextBuilder
      ↓
SearchManager
      ↓
 ┌───────────────┐
 │               │
 ▼               ▼
Fuzzy         Semantic
Search        Search
 │               │
 └───────┬───────┘
         ▼
      Merger
         ↓
    DB Hydration
         ↓
    RAG Context
```

## Files

```text
search/
├── context_builder.py
├── search_manager.py
├── fuzzy_search.py
├── semantic_search.py
├── merger.py
├── search_utils.py
├── preprocess.py
└── db_queries.py
```

### `context_builder.py`

Coordinates the search flow and builds the final context used by the RAG node.

It:

1. Normalizes refined queries.
2. Runs the search.
3. Fetches the complete lab records.
4. Formats them into the final context.

### `search_manager.py`

Runs both search methods for every refined query:

```text
Fuzzy Search    → 2 results
Semantic Search → 3 results
```

Then it:

```text
Merge
  ↓
Sort by score
  ↓
Keep top 50
```

### `fuzzy_search.py`

Searches using text similarity.

It compares:

```text
Name
Aliases
Keywords
```

using RapidFuzz and character n-grams.

Weights:

```text
Name     = 1.00
Alias    = 0.95
Keyword  = 0.85
```

Minimum score:

```text
0.45
```

### `semantic_search.py`

Creates an embedding for the refined query and searches Qdrant for semantically similar laboratory services.

Returns the top 3 results.

### `merger.py`

Combines fuzzy and semantic results.

If the same lab is found by both methods, its score gets a `1.15` boost, capped at `1.0`.

Duplicate lab IDs are reduced to one result.

### `search_utils.py`

Prepares the search terms from:

```text
query + aliases + keywords
```

and normalizes them before fuzzy search.

### `preprocess.py`

Contains the text preprocessing utilities:

* Text normalization
* Character n-gram generation
* N-gram similarity

### `db_queries.py`

Handles database retrieval for the search pipeline.

It provides:

```text
get_all_active_lab_services_for_search()
```

for lightweight search data, and:

```text
get_lab_services_by_ids()
```

for loading the complete lab records after search.

## Important

The search module only handles **retrieval**.

It does not decide the user's intent and does not generate the final chatbot response.
