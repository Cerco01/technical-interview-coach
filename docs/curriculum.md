# Curriculum Map

`curriculum/topics.json` is the selection index used by the coach. It provides stable, client-neutral topic IDs for a general Data Science, Machine Learning, and AI interview curriculum.

## Design

The 37-topic taxonomy covers programming foundations, NumPy, data science, machine learning, deep learning, deployment, and end-to-end project work. NumPy is independent because array shapes, axes, broadcasting, dtypes, reductions, masking, and vectorization are distinct interview competencies. Git and data visualization remain separate, as do SQL and SQLAlchemy.

## Selection Fields

| Field | Meaning |
| --- | --- |
| `id` | Stable reference used by questions and learner progress |
| `domain` | Broad curriculum section |
| `priority` | `core`, `secondary`, or `advanced` interview value |
| `status` | `available` has curated MVP questions; `planned` is mapped but not yet banked |
| `prerequisites` | Topic IDs that should usually be understood first |
| `competencies` | Representative concepts assessed within the topic |

`available` means at least one curated question references the topic. `planned` topics remain valid curriculum entries but are intentionally not presented as covered by the initial bank.
