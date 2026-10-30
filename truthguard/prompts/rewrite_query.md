# Rewrite Query

You are parsing a user question for a policy document retrieval system.
Produce 2–3 clean rewrites in English (and in Hindi too if the question is Hindi or Hinglish).

Question: {{question}}

Return a JSON object:
{
  "question_language": "en" | "hi" | "mixed",
  "rewrites": ["...", "..."],
  "concept_phrase": "...",
  "scope_tags": "...",
  "as_of": "YYYY-MM-DD or null"
}
